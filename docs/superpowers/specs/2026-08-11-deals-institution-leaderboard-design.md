# Deals Institution Leaderboard Design

**Date:** 2026-08-11  
**Scope:** Restore the institution-level bought-stock preview and TradingView copy action in the Deals tab, while removing wasted width from the leaderboard.

## Goal

The Institution leaderboard must show the stocks associated with each institution in the selected advanced-deals window, ordered from the institution's most recent stock activity to its oldest. Each row must provide a compact copy icon that copies the complete ordered list as `NSE:SYMBOL,...` for TradingView.

## Current regression

The generic NiceGUI table renderer already has a `copy_symbols` body slot that reads a hidden `symbol_list` field. The Deals page currently does not return that field from the institution query and calls the renderer with `copy_symbols=False`. The generic table also uses wide minimums and an auto-layout table, allowing the text column to absorb most of the available viewport.

## Design

### Data flow

1. `query_deals_advanced()` builds the existing filtered deal window.
2. A grouped client/symbol relation computes each institution-symbol pair's latest deal date.
3. A client-level aggregation produces:
   - the existing metrics;
   - `symbols`, the distinct stock count;
   - `symbol_list`, the full ordered TradingView list using `NSE:` prefixes and underscore normalization.
4. The Deals page derives a short `symbol_preview` from `symbol_list` for display and adds a `copy_symbols` placeholder column for the existing table slot.

The ordering rule is deterministic: descending maximum `trade_date` for each institution-symbol pair, then ascending symbol for ties. The stock list follows the active Side filter and lookback window, so BUY mode lists stocks bought by that institution.

### Presentation

The institution table will use the existing renderer with a new opt-in compact mode. Compact mode is scoped to this table and uses fixed, intentional widths so the institution name and stock preview remain readable without allowing the stock column to stretch across the viewport.

Visible order:

`Institution | Latest Deal | Buy Cr | Sell Cr | Net Cr | Active Days | Copy | Stocks`

The Stocks cell shows a short comma-separated preview followed by `+N more` when needed. The full list is retained in the hidden `symbol_list` row field. The Copy header is narrow and its row content is the existing copy icon.

### Error handling

- Institutions with no symbols are not expected from the grouped query; if an empty list reaches the table, the icon keeps the existing “No symbols to copy” warning behavior.
- Null or malformed symbols are excluded from the aggregated copy list.
- If the advanced query fails because of the optional aggregation, the existing query error behavior remains unchanged; no open-path query is affected.
- Existing stock-deals table behavior and global table widths remain unchanged unless compact mode is explicitly enabled.

## Testing

- Extend `tests/test_deals_desk.py` to assert institution rows include an ordered symbol list, including a case where one institution has symbols on multiple dates.
- Assert the generated copy list uses TradingView `NSE:` prefixes and keeps newest activity first.
- Add source-level regression assertions that the Deals page enables the copy column and requests compact mode.
- Run the focused Deals tests, then the full test suite and a Python compile check for changed modules.

## Acceptance criteria

- The Institution leaderboard shows a final Stocks column with newest-to-oldest stocks per institution.
- A compact copy icon is present for every institution row and copies the full ordered TradingView list.
- The leaderboard no longer gives most of the viewport to one text column.
- The default Deals page query budget and existing BUY TV list behavior remain unchanged.
- No unrelated tables change layout.
