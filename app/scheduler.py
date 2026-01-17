
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

# Timezone de México para los reportes
MX_TZ = pytz.timezone("America/Monterrey")

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


# ============================================================================
# SOCIAL MONITORING TICK - Procesa fuentes de redes sociales con Apify
# ============================================================================
async def social_monitoring_tick():
    """
    Ejecuta el pipeline de monitoreo de redes sociales para todas las campañas
    que tengan fuentes activas. Se ejecuta una vez al día (en la madrugada).

    Flujo:
    1. Obtiene campañas con MonitoringSources activas
    2. Para cada campaña, ejecuta el pipeline Apify → Perplexity → BD
    3. Registra resultados y errores
    """
    from .services.social_analysis_service import run_campaign_monitoring_pipeline

    log.info("🔄 Iniciando social_monitoring_tick")

    async with SessionLocal() as session:
        # Obtener campañas que tienen fuentes de monitoreo activas
        query = (
            select(models.Campaign.id)
            .join(models.MonitoringSource)
            .where(models.MonitoringSource.status == models.MonitoringStatus.ACTIVE)
            .distinct()
        )
        result = await session.execute(query)
        campaign_ids = [row[0] for row in result.all()]

        if not campaign_ids:
            log.info("📭 No hay campañas con fuentes de monitoreo activas")
            return

        log.info(f"📊 Procesando {len(campaign_ids)} campañas con monitoreo social")

        for campaign_id in campaign_ids:
            try:
                log.info(f"🚀 Procesando campaña: {campaign_id}")

                # Ejecutar pipeline con nueva sesión para cada campaña
                async with SessionLocal() as campaign_session:
                    result = await run_campaign_monitoring_pipeline(
                        campaign_id=campaign_id,
                        db=campaign_session,
                        days_back=1,  # Solo últimas 24 horas
                        max_posts_per_source=50,
                    )

                    if result.get("success"):
                        log.info(
                            f"✅ Campaña {campaign_id}: "
                            f"{result.get('posts_found', 0)} posts, "
                            f"{result.get('results_saved', 0)} guardados"
                        )
                    else:
                        log.warning(f"⚠️ Campaña {campaign_id}: {result.get('error', 'Unknown error')}")

            except Exception as e:
                log.error(f"❌ Error procesando campaña {campaign_id}: {e}")
                continue

        log.info("✅ social_monitoring_tick completado")


# ============================================================================
# DAILY REPORT TICK - Genera reportes diarios automáticamente
# ============================================================================
async def daily_report_tick():
    """
    Genera reportes diarios para todas las campañas con monitoreo activo.
    Se ejecuta todos los días a las 6:00 AM (después del social_monitoring_tick).

    El reporte incluye:
    - Noticias del día anterior
    - Posts de redes sociales del día anterior
    - Análisis de sentimiento
    - Alertas de riesgo
    """
    from .services.campaign_report_service import generate_and_save_daily_report

    log.info("📊 Iniciando daily_report_tick")

    # Generar reporte del día anterior
    yesterday = date.today() - timedelta(days=1)

    async with SessionLocal() as session:
        # Obtener campañas con monitoreo activo o con autoEnabled
        query = (
            select(models.Campaign.id)
            .where(models.Campaign.autoEnabled == True)
        )
        result = await session.execute(query)
        campaign_ids = [row[0] for row in result.all()]

        if not campaign_ids:
            log.info("📭 No hay campañas activas para generar reportes diarios")
            return

        log.info(f"📊 Generando reportes diarios para {len(campaign_ids)} campañas")

        for campaign_id in campaign_ids:
            try:
                async with SessionLocal() as report_session:
                    result = await generate_and_save_daily_report(
                        campaign_id=campaign_id,
                        report_date=yesterday,
                        db=report_session,
                    )

                    if result.get("success"):
                        log.info(f"✅ Reporte diario generado para campaña {campaign_id}")
                    else:
                        log.warning(f"⚠️ Error en reporte diario: {result.get('error')}")

            except Exception as e:
                log.error(f"❌ Error generando reporte diario para {campaign_id}: {e}")
                continue

        log.info("✅ daily_report_tick completado")


# ============================================================================
# WEEKLY REPORT TICK - Genera reportes semanales los lunes
# ============================================================================
async def weekly_report_tick():
    """
    Genera reportes semanales para todas las campañas con monitoreo activo.
    Se ejecuta todos los lunes a las 7:00 AM.

    El reporte incluye:
    - Resumen de la semana anterior (lunes a domingo)
    - Tendencias de sentimiento día a día
    - Comparativa con la semana anterior
    - Narrativas principales
    - Análisis de riesgo
    """
    from .services.campaign_report_service import generate_and_save_weekly_report

    log.info("📊 Iniciando weekly_report_tick")

    # La semana anterior termina el domingo pasado
    today = date.today()
    # Calcular el domingo pasado (si hoy es lunes, es ayer)
    days_since_sunday = (today.weekday() + 1) % 7
    if days_since_sunday == 0:
        days_since_sunday = 7  # Si hoy es domingo, usamos el domingo anterior
    last_sunday = today - timedelta(days=days_since_sunday)

    log.info(f"📅 Generando reportes semanales para semana que terminó: {last_sunday}")

    async with SessionLocal() as session:
        # Obtener campañas activas
        query = (
            select(models.Campaign.id)
            .where(models.Campaign.autoEnabled == True)
        )
        result = await session.execute(query)
        campaign_ids = [row[0] for row in result.all()]

        if not campaign_ids:
            log.info("📭 No hay campañas activas para generar reportes semanales")
            return

        log.info(f"📊 Generando reportes semanales para {len(campaign_ids)} campañas")

        for campaign_id in campaign_ids:
            try:
                async with SessionLocal() as report_session:
                    result = await generate_and_save_weekly_report(
                        campaign_id=campaign_id,
                        week_end_date=last_sunday,
                        db=report_session,
                    )

                    if result.get("success"):
                        log.info(f"✅ Reporte semanal generado para campaña {campaign_id}")
                    else:
                        log.warning(f"⚠️ Error en reporte semanal: {result.get('error')}")

            except Exception as e:
                log.error(f"❌ Error generando reporte semanal para {campaign_id}: {e}")
                continue

        log.info("✅ weekly_report_tick completado")


async def schedule_campaigns():
    if scheduler is None:
        return
    # Run campaign ingestion every hour at HH:05
    scheduler.add_job(campaign_tick, CronTrigger(minute="5"))

    # Run social monitoring once a day at 3:00 AM (hora de Monterrey)
    # Esto permite procesar posts de las últimas 24 horas sin interferir con horarios pico
    scheduler.add_job(
        social_monitoring_tick,
        CronTrigger(hour="3", minute="0", timezone=MX_TZ),
        id="social_monitoring_daily",
        replace_existing=True,
    )

    # Generar reportes diarios a las 6:00 AM (después del social monitoring)
    scheduler.add_job(
        daily_report_tick,
        CronTrigger(hour="6", minute="0", timezone=MX_TZ),
        id="daily_report_generation",
        replace_existing=True,
    )

    # Generar reportes semanales los lunes a las 7:00 AM
    scheduler.add_job(
        weekly_report_tick,
        CronTrigger(day_of_week="mon", hour="7", minute="0", timezone=MX_TZ),
        id="weekly_report_generation",
        replace_existing=True,
    )

    log.info(
        "📅 Scheduled: campaign_tick (HH:05), "
        "social_monitoring_tick (03:00 MX), "
        "daily_report_tick (06:00 MX), "
        "weekly_report_tick (lunes 07:00 MX)"
    )