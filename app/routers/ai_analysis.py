# app/routers/ai_analysis.py
from fastapi import APIRouter, Query, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Any, Dict
import httpx, urllib.parse, time, datetime, hashlib, uuid
import feedparser

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..db import get_session
from .. import models
from ..services.llm import analyze_snippet

router = APIRouter(prefix="/ai", tags=["ai"])

class AnalyzedItem(BaseModel):
    title: str
    link: str
    source: Optional[str] = None
    published_at: Optional[datetime.datetime] = None
    llm: Dict[str, Any]

class AnalyzeResponse(BaseModel):
    query: str
    total: int
    items: List[AnalyzedItem]

def build_google_news_rss(query: str, lang: str = "es-419", country: str = "MX") -> str:
    q = f"\"{query}\""
    params = {"q": q, "hl": lang, "gl": country, "ceid": f"{country}:{lang}"}
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)

def _to_dt(struct_time) -> Optional[datetime.datetime]:
    try:
        if struct_time:
            return datetime.datetime.fromtimestamp(time.mktime(struct_time), tz=datetime.timezone.utc)
    except Exception:
        return None
    return None

def clean_link(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.netloc.endswith("news.google.com"):
            qs = urllib.parse.parse_qs(parsed.query)
            if "url" in qs and qs["url"]:
                return qs["url"][0]
    except Exception:
        pass
    return url

@router.get("/analyze-news", response_model=AnalyzeResponse)
async def analyze_news(
    q: str = Query(..., min_length=2, description="Actor político o frase exacta"),
    size: int = Query(35, ge=1, le=50),
    days_back: int = Query(14, ge=1, le=90),
    lang: str = Query("es-419"),
    country: str = Query("MX"),
    campaignId: Optional[str] = Query(None, description="Si lo envías, guarda los análisis ligados a la campaña"),
    session: AsyncSession = Depends(get_session)
):
    # 1) obtener feed
    rss_url = build_google_news_rss(q, lang=lang, country=country)
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(rss_url)
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Error Google News RSS ({resp.status_code})")
    feed = feedparser.parse(resp.content)
    if feed.bozo:
        raise HTTPException(status_code=502, detail="No se pudo parsear el feed RSS")

    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_back)

    # 2) filtrar/limitar
    entries = []
    for e in feed.entries:
        dt = _to_dt(getattr(e, "published_parsed", None))
        if dt and dt < cutoff:
            continue
        title = getattr(e, "title", "").strip()
        link = clean_link(getattr(e, "link", "").strip())
        summary = getattr(e, "summary", "") or ""
        source = None
        try:
            source = e.source.title  # type: ignore
        except Exception:
            pass
        if title and link:
            entries.append((title, summary, link, source, dt))
        if len(entries) >= size:
            break

    # 3) LLM por item (sin streaming para mantenerlo simple)
    analyzed: List[AnalyzedItem] = []
    for title, summary, link, source, dt in entries:
        llm_json = analyze_snippet(title=title, summary=summary, actor=q)
        analyzed.append(AnalyzedItem(
            title=title, link=link, source=source, published_at=dt, llm=llm_json
        ))

    # 4) Guardar en BD (opcional)
    if campaignId and analyzed:
        cres = await session.execute(select(models.Campaign).where(models.Campaign.id == campaignId))
        campaign = cres.scalar_one_or_none()
        if not campaign:
            raise HTTPException(status_code=404, detail="campaignId no existe")

        saved = 0
        for item in analyzed:
            h = hashlib.sha256(item.link.encode()).hexdigest()
            # ¿ya existe IngestedItem?
            exists = await session.execute(select(models.IngestedItem).where(models.IngestedItem.hash == h))
            ing = exists.scalar_one_or_none()
            if not ing:
                ing = models.IngestedItem(
                    id=str(uuid.uuid4()),
                    campaignId=campaignId,
                    sourceType=models.SourceType.NEWS,
                    sourceUrl=item.link,
                    contentUrl=item.link,
                    author=None,
                    title=item.title,
                    excerpt=None,
                    publishedAt=item.published_at,
                    status=models.ItemStatus.PROCESSED,
                    hash=h
                )
                session.add(ing)
                await session.flush()

            # guarda/actualiza Analysis ligado al item
            # asumiendo columna JSON en models.Analysis.result (o similar)
            existing = await session.execute(
                select(models.Analysis).where(models.Analysis.itemId == ing.id)
            )
            ana = existing.scalar_one_or_none()
            if ana:
                ana.result = item.llm  # dict JSON
            else:
                session.add(models.Analysis(
                    id=str(uuid.uuid4()),
                    itemId=ing.id,
                    result=item.llm,
                    model="gpt-5-mini",
                    analysisType="news_sentiment"
                ))
            saved += 1
        if saved:
            await session.commit()

    return AnalyzeResponse(query=q, total=len(analyzed), items=analyzed)