"""MarketPulse API v2 (spec §8). Mount `router` on the main app; `create_app()` builds a v2-only app
(used by tests and by Scripts/export_openapi.py)."""
from __future__ import annotations

from fastapi import FastAPI

from App.api.v2.routes import API_VERSION, router
from App.api.v2.routes_pulse import router as _pulse_router; router.include_router(_pulse_router)  # noqa: E702 Pulse tab
router.include_router(__import__("App.api.v2.routes_setups", fromlist=["router"]).router)  # Setups tab
from App.api.v2 import routes_sectors  # noqa: E402,F401  Sector Intel (/api/v2/sectors/*)
from App.api.v2.routes_deals import router as _deals_router; router.include_router(_deals_router)  # noqa: E402,E702  Deals tab
import App.api.v2.routes_charts  # noqa: F401,E402  Charts tab: registers its router on `router`
from App.api.v2 import routes_research  # noqa: E402,F401  Research tab endpoints (registers on router)
from App.api.v2 import routes_divergence  # noqa: E402,F401  RSI divergences (charts + setups scanner)

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
