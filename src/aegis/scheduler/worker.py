"""Standalone scheduler worker process.

Run with: python -m aegis.scheduler.worker
Used when running the scheduler separately from the API (e.g. on Fly.io).
"""

import asyncio

from loguru import logger

from aegis.db.engine import close_pool, get_pool
from aegis.logging import setup_logging
from aegis.scheduler.apscheduler_runner import schedule_briefing, start_scheduler, stop_scheduler


async def _run_briefing():
    from aegis.briefing.service import BriefingService
    result = await BriefingService().run(trigger_source="cron")
    logger.info(
        "Cron briefing complete: run_id={}, status={}, cost=${}",
        result.get("run_id"),
        result.get("status"),
        result.get("total_cost_usd"),
    )


async def main():
    setup_logging()
    await get_pool()
    schedule_briefing(_run_briefing)
    start_scheduler()
    logger.info("Scheduler worker running. Waiting for jobs...")
    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler worker shutting down")
    finally:
        stop_scheduler()
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
