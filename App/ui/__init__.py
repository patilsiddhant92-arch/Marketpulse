"""MarketPulse UI kit (styles, shell, widgets)."""

try:
    from App.ui.styles import add_styles, add_deals_desk_styles
except ModuleNotFoundError:
    from ui.styles import add_styles, add_deals_desk_styles  # type: ignore

__all__ = ["add_styles", "add_deals_desk_styles"]
