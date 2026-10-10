"""MarketPulse API v2 (spec §8). Mount `router` on the main app; `create_app()` builds a v2-only app
(used by tests and by Scripts/export_openapi.py)."""
from __future__ import annotations

from fastapi import FastAPI

from App.api.v2.routes import API_VERSION, router
import App.api.v2.routes_charts  # noqa: F401,E402  Charts tab: registers its router on `router`

__all__ = ["router", "create_app", "API_VERSION"]


def create_app() -> FastAPI:
    app = FastAPI(
        title="MarketPulse API v2",
        version=API_VERSION,
        description="EOD swing-trading data for NSE stocks. Envelope {as_of, freshness, total, returned, rows, meta}; "
                    "NULL stays NULL; every read accepts as_of (time travel).",
    )
    app.include_router(router)
    return app
