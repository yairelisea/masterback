
import os, asyncio, logging, pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from .db import SessionLocal
from . import models
from datetime import datetime, timezone, date, timedelta
from .services.ingest_auto import kickoff_campaign_ingest

log = logging.getLogger("scheduler")
scheduler: AsyncIOScheduler | None = None

async def start_scheduler():
    global scheduler
    if os.getenv("RUN_SCHEDULER", "true").lower() != "true":
        return
    if scheduler is None:
        scheduler = AsyncIOScheduler()
        scheduler.start()
        # Removed load_alerts_and_schedule()

def _today_mx() -> date:
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
    if c.lastAutoRunAt:
        delta = now - c.lastAutoRunAt
        if delta.total_seconds() < 4*3600:
            return False
    return True

async def campaign_tick():
    async with SessionLocal() as session:  # ✅ FIX: Usar SessionLocal directamente
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
            
            await kickoff_campaign_ingest(c.id)
            
            c.autoRunsToday = (c.autoRunsToday or 0) + 1
            c.lastAutoRunAt = now
        await session.commit()

async def schedule_campaigns():
    if scheduler is None:
        return
    # Run every hour
    scheduler.add_job(campaign_tick, CronTrigger(minute="5"))  # HH:05 every hour