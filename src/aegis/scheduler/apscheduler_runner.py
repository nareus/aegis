"""APScheduler setup for cron-triggered agent runs."""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from aegis.config import settings

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


def schedule_briefing(callback) -> None:
    """Schedule the briefing agent on the configured cron expression."""
    scheduler = get_scheduler()
    parts = settings.aegis_briefing_cron.split()
    if len(parts) != 5:
        logger.error("Invalid AEGIS_BRIEFING_CRON: {}", settings.aegis_briefing_cron)
        return

    trigger = CronTrigger(
        minute=parts[0],
        hour=parts[1],
        day=parts[2],
        month=parts[3],
        day_of_week=parts[4],
        timezone=settings.aegis_timezone,
    )
    scheduler.add_job(callback, trigger, id="daily_briefing", replace_existing=True)
    logger.info("Scheduled daily briefing with cron: {}", settings.aegis_briefing_cron)


def start_scheduler() -> None:
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler stopped")
