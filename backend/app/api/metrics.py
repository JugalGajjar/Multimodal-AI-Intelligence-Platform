"""Prometheus scrape endpoint."""

from fastapi import APIRouter
from fastapi.responses import Response

from app.core.metrics import render_metrics

router = APIRouter(tags=["metrics"])


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)
