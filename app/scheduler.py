# app/scheduler.py
import os, asyncio, hashlib, uuid, logging, pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from .db import get_session
from . import models
from .services.news_fetcher import fetch_news
from .services.llm import analyze_snippet, aggregate_perspective

log = logging.getLogger("scheduler")
scheduler: AsyncIOScheduler | None = None

async def run_alert(alert: models.Alert):
    async with get_session() as session:
        # cargar queries de la alerta
        qres = await session.execute(select(models.AlertQuery).where(models.AlertQuery.alertId == alert.id))
        queries = qres.scalars().all()
        if not queries:
            log.info("Alert %s sin queries, saltando", alert.id)
            return

        total_new = 0
        analyzed_payloads = []  # para aggregate opcional
        for aq in queries:
            items = await fetch_news(
                aq.q,
                size=aq.size,
                days_back=aq.daysBack,
                lang=aq.lang,
                country=aq.country,
                city_keywords=aq.cityKeywords or []
            )

            for it in items:
                h = hashlib.sha256(it.link.encode()).hexdigest()
                dup = await session.execute(select(models.IngestedItem).where(models.IngestedItem.hash == h))
                if dup.scalar_one_or_none():
                    continue

                ing = models.IngestedItem(
                    id=str(uuid.uuid4()),
                    campaignId=alert.campaignId,
                    sourceType=models.SourceType.NEWS,
                    sourceUrl=it.link,
                    contentUrl=it.link,
                    author=None,
                    title=it.title,
                    excerpt=it.summary,
                    publishedAt=it.published_at,
                    status=models.ItemStatus.PROCESSED if alert.analyze else models.ItemStatus.QUEUED,
                    hash=h
                )
                session.add(ing)
                await session.flush()

                if alert.analyze:
                    try:
                        llm = analyze_snippet(title=it.title, summary=it.summary or "", actor=aq.q)
                        session.add(models.Analysis(
                            id=str(uuid.uuid4()),
                            itemId=ing.id,
                            result=llm,
                            model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
                            analysisType="news_sentiment"
                        ))
                        analyzed_payloads.append({
                            "title": it.title,
                            "source": it.source,
                            "published_at": it.published_at.isoformat() if it.published_at else None,
                            "llm": llm
                        })
                    except Exception as e:
                        log.error("LLM fallo en alerta %s: %s", alert.id, e)

                total_new += 1

        aggregate = None
        if alert.analyze and analyzed_payloads:
            try:
                aggregate = aggregate_perspective(actor=f"Alerta:{alert.name}", analyzed_items=analyzed_payloads)
            except Exception as e:
                log.error("Aggregate fallo en alerta %s: %s", alert.id, e)

        session.add(models.AlertNotification(
            alertId=alert.id,
            itemsCount=total_new,
            aggregate=aggregate
        ))
        await session.commit()
        log.info("Alert %s completada: %d nuevos items", alert.name, total_new)

async def schedule_alert(alert: models.Alert):
    tz = pytz.timezone(alert.timezone or "America/Monterrey")
    trigger = CronTrigger.from_crontab(alert.scheduleCron, timezone=tz)
    scheduler.add_job(run_alert, trigger, args=[alert], id=alert.id, replace_existing=True)
    log.info("Programada alerta %s (%s %s)", alert.name, alert.scheduleCron, alert.timezone)

async def load_alerts_and_schedule():
    async with get_session() as session:
        res = await session.execute(select(models.Alert).where(models.Alert.isActive == True))
        for alert in res.scalars().all():
            await schedule_alert(alert)

async def start_scheduler():
    global scheduler
    if os.getenv("RUN_SCHEDULER", "true").lower() != "true":
        return
    if scheduler is None:
        scheduler = AsyncIOScheduler()
        scheduler.start()
        await load_alerts_and_schedule()

    
from datetime import datetime, timezone, date, timedelta
from .services.ingest_auto import kickoff_campaign_ingest

def _today_mx() -> date:
    # America/Monterrey approx by UTC conversion; if pytz used already, OK.
    tz = pytz.timezone("America/Monterrey")
    return datetime.now(tz).date()

async def _reset_quota_if_needed(session: AsyncSession, c: models.Campaign, today: date) -> None:
    if c.autoLastReset is None or (c.autoLastReset.date() if isinstance(c.autoLastReset, datetime) else c.autoLastReset) != today:
        c.autoRunsToday = 0
        c.autoLastReset = datetime.now(tz=pytz.timezone("America/Monterrey"))

def _quota_for_plan(plan: models.PlanTier) -> int | None:
    if plan == models.PlanTier.BASIC:
        return 1
    if plan == models.PlanTier.PRO:
        return 3
    return None  # UNLIMITED

def _should_run_now(c: models.Campaign, now: datetime) -> bool:
    # Minimal spacing: 4h between runs to avoid hammering
    if c.lastAutoRunAt:
        delta = now - c.lastAutoRunAt
        if delta.total_seconds() < 4*3600:
            return False
    return True

async def campaign_tick():
    async with get_session() as session:
        res = await session.execute(select(models.Campaign).where(models.Campaign.autoEnabled == True))
        campaigns = res.scalars().all()
        today = _today_mx()
        now = datetime.now(tz=pytz.timezone("America/Monterrey"))
        for c in campaigns:
            await _reset_quota_if_needed(session, c, today)
            quota = _quota_for_plan(c.plan)
            if quota is not None and c.autoRunsToday >= quota:
                continue
            if not _should_run_now(c, now):
                continue
            # Fire and update counters
            await kickoff_campaign_ingest(c.id)
            try:
                # Procesa pendientes apenas se ingesta
                from .routers.analyses_extra import process_pending as _process_pending
                await _process_pending(campaignId=c.id, limit=200, db=session)  # type: ignore
            except Exception:
                pass
            c.autoRunsToday = (c.autoRunsToday or 0) + 1
            c.lastAutoRunAt = now
        await session.commit()

async def schedule_campaigns():
    if scheduler is None:
        return
    # Run every hour
    scheduler.add_job(campaign_tick, CronTrigger(minute="5"))  # HH:05 every hour
