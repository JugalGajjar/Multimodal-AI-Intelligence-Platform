from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from app import __version__
from app.api.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.core.middleware import HttpMetricsMiddleware, RequestIdMiddleware
from app.core.tracing import configure_tracing


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield


def create_app() -> FastAPI:
    configure_logging("DEBUG" if settings.app_debug else "INFO")
    configure_tracing(settings.otel_service_name)

    app = FastAPI(
        title="Multimodal AI Intelligence Platform",
        version=__version__,
        debug=settings.app_debug,
        lifespan=lifespan,
    )

    # Order matters: request_id wraps everything; metrics is innermost so
    # the labels see the resolved route template.
    app.add_middleware(HttpMetricsMiddleware)
    app.add_middleware(RequestIdMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    app.include_router(api_router, prefix="/api/v1")

    # FastAPI instrumentation creates spans for every route handler.
    FastAPIInstrumentor.instrument_app(app, excluded_urls="/api/v1/metrics,/api/v1/health")
    return app


app = create_app()
