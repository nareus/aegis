"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from aegis.config import settings
from aegis.db.engine import close_pool, get_pool
from aegis.logging import setup_logging


def _warn_config() -> None:
    from loguru import logger
    warnings = settings.check()
    if warnings:
        logger.warning("Aegis config warnings — some features may not work:")
        for w in warnings:
            logger.warning(w)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    _warn_config()
    await get_pool()
    yield
    await close_pool()


def create_app() -> FastAPI:
    app = FastAPI(title="Aegis", version="0.1.0", lifespan=lifespan)

    from aegis.api.health import router as health_router
    from aegis.api.briefing import router as briefing_router
    from aegis.api.jobs import router as jobs_router
    from aegis.api.traces import router as traces_router

    app.include_router(health_router)
    app.include_router(briefing_router)
    app.include_router(jobs_router)
    app.include_router(traces_router)

    return app


app = create_app()
