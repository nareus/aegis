"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from aegis.db.engine import close_pool, get_pool
from aegis.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    await get_pool()
    yield
    await close_pool()


def create_app() -> FastAPI:
    app = FastAPI(title="Aegis", version="0.1.0", lifespan=lifespan)

    from aegis.api.health import router as health_router
    from aegis.api.briefing import router as briefing_router

    app.include_router(health_router)
    app.include_router(briefing_router)

    return app


app = create_app()
