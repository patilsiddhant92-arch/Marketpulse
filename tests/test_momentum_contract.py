from pathlib import Path


def test_momentum_summary_respects_user_market_cap_filter_and_labels_volume_inputs():
    source = Path("App/app.py").read_text(encoding="utf-8")

    assert "tradable = tradable[pd.to_numeric(tradable[\"market_cap_cr\"], errors=\"coerce\").fillna(0) >= float(min_mcap.value or 0)]" in source
    assert 'ui.number("Day volume"' in source
    assert 'ui.number("20D avg volume"' in source


def test_momentum_debug_symbol_search_and_autocomplete():
    source = Path("App/app.py").read_text(encoding="utf-8")

    # Verify debug_symbol is a searchable select with stock autocomplete options
    assert 'debug_symbol = ui.select(' in source
    assert 'options=get_stocks_search_options()' in source
    assert 'with_input=True' in source
    assert 'new_value_mode="add"' in source
    assert 'debug_container = ui.column().classes("w-full")' in source
    assert 'debug_symbol.on_value_change(_on_debug_symbol_change)' in source

    # Verify run_symbol_debug paints to debug_container so container.clear() does not wipe it
    assert 'with debug_container:' in source
    assert 'debug_container.clear()' in source


def test_stocks_search_options_labels_cover_symbols_and_names():
    import sys
    sys.path.insert(0, "App")
    from app import get_stocks_search_options

    opts = get_stocks_search_options()
    assert len(opts) > 500
    assert "RELIANCE" in opts
    assert "TCS" in opts
    assert "SBIN" in opts

    # Verify both symbol code and company name appear in the label so user searches by either letter or name
    assert "RELIANCE" in opts["RELIANCE"]
    assert "reliance industries" in opts["RELIANCE"].lower()
    assert "TCS" in opts["TCS"]
    assert "tata consultancy" in opts["TCS"].lower()
    assert "SBIN" in opts["SBIN"]
    assert "state bank of india" in opts["SBIN"].lower()


def test_resolve_stock_symbol_resolution():
    import sys
    sys.path.insert(0, "App")
    from app import resolve_stock_symbol

    # 1. Exact symbols (case-insensitive)
    assert resolve_stock_symbol("RELIANCE") == "RELIANCE"
    assert resolve_stock_symbol("reliance") == "RELIANCE"
    assert resolve_stock_symbol("sbin") == "SBIN"
    assert resolve_stock_symbol("TCS") == "TCS"
    assert resolve_stock_symbol("infy") == "INFY"

    # 2. Symbol prefix matches (e.g. sbi -> SBIN)
    assert resolve_stock_symbol("sbi") == "SBIN"
    assert resolve_stock_symbol("reli") == "RELIANCE"

    # 3. Company name match
    assert resolve_stock_symbol("State Bank of India") == "SBIN"
    assert resolve_stock_symbol("state bank") == "SBIN"
    assert resolve_stock_symbol("Tata Steel") == "TATASTEEL"
    assert resolve_stock_symbol("Infosys") == "INFY"

    # 4. Composite option label format
    assert resolve_stock_symbol("SBIN · STATE BANK OF INDIA (Financial Services)") == "SBIN"
    assert resolve_stock_symbol("TCS · TATA CONSULTANCY SERVICES (Information Technology)") == "TCS"

    # 5. Unknown / None / Empty
    assert resolve_stock_symbol(None) is None
    assert resolve_stock_symbol("") is None
    assert resolve_stock_symbol("   ") is None
    assert resolve_stock_symbol("UNKNOWN_TICKER_123") == "UNKNOWN_TICKER_123"


def test_stocks_search_options_cache_immutability():
    import sys
    sys.path.insert(0, "App")
    from app import get_stocks_search_options

    opts1 = get_stocks_search_options()
    opts1["CORRUPT_KEY"] = "CORRUPT_VALUE"

    opts2 = get_stocks_search_options()
    assert "CORRUPT_KEY" not in opts2, "get_stocks_search_options() returned a mutable reference to internal cache!"


def test_momentum_uncommitted_input_and_key_generator_contract():
    source = Path("App/app.py").read_text(encoding="utf-8")

    # Contract requires key_generator to resolve raw inputs (e.g. company names)
    assert "key_generator=lambda x: resolve_stock_symbol(x) or str(x).upper().strip()" in source
    # Contract requires input-value event listener to catch text typed without blur/commit
    assert 'debug_symbol.on("input-value", _on_debug_input)' in source
    # Contract requires render() to inspect uncommitted text tracker before fallback to value
    assert 'current_debug_input["text"]' in source
    assert 'target_sym = resolve_stock_symbol(current_debug_input["text"])' in source


