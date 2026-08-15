"""Research specialist pages (Sector / Momentum / Deals)."""

try:
    from App.pages.research.deals import build_deals_page
    from App.pages.research.sector_intel import build_sector_intel_page
except ModuleNotFoundError:
    from pages.research.deals import build_deals_page  # type: ignore
    from pages.research.sector_intel import build_sector_intel_page  # type: ignore

__all__ = ["build_deals_page", "build_sector_intel_page"]

