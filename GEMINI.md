# MarketPulse Project Invariants & Engineering Guidelines

## MarketPulse Trading & UI Invariants

1. **Table Symbol Copying Must Never Silently Truncate**:
   - When generating symbol export lists from tables displaying screener or research results (such as `table_from_df`), never silently drop stocks using default filters (`require_above_ema200=True` or `min_mcap_cr=900`).
   - If a stock is visible in the UI table (e.g. Stage 1 turnaround setups or small-cap momentum), clicking "Copy Symbols" must copy 100% of visible symbols (`min_mcap_cr=None, require_above_ema200=False`).

2. **Clipboard Callback Signature Flexibility**:
   - Clipboard helpers like `copy_text_to_clipboard` must support both single-argument `(text)` and dual-argument `(label, text)` signatures to prevent `TypeError` exceptions across varying button handler signatures.

3. **No Artificial Stop-Loss Filtering in Screeners**:
   - Screeners and Action Desk queues must never filter out setups based on arbitrary stop-loss distances. Risk parameters and stop-loss calculations belong to the trader's execution layer, not the initial discovery funnel.

4. **Float & Near-Zero Formatting Safeguards**:
   - Any financial float formatting (e.g. `net_cr` in institutional deals) must apply a deadband for near-zero values (`abs(val) < 0.05 => 0.0, sign = '+'`) to eliminate contradictory signs or visual artifacts like `-0.0Cr (+)`.

5. **DuckDB Cache Invalidation on Session Ingestion**:
   - In-memory dataset caches keyed by 'latest' or omitted session dates must incorporate the underlying `.duckdb` file's modification timestamp (`st_mtime_ns`) so that any session ingestion automatically evicts stale caches.

6. **Manas Arora Volatility Contraction Pattern (VCP) Engine**:
   - The VCP Screener and Action Desk primary queue must detect progressive contraction waves (e.g. `T1 > T2 > T3` depth) and Volume Dry-Up (`VDU ratio ≤ 0.80`) in the right-hand base rather than relying on raw single-day shakeout flags or arbitrary 1M volume cutoffs.
   - All VCP candidates must operate within a Stage 2 technical template: trading above the 200 EMA (`close > ema_200`), within 25% of 52-week highs (`away_52w_high_pct >= -25%`), and showing supply exhaustion before pivot breakout.
   - **Pivot & Risk Rules**: Trigger entry must align with the pivot resistance breakout level (or tight coil cheat entry near 10/20 EMA); Stop Loss is placed at the swing low of the final contraction wave (or 10/20 EMA floor) to ensure controlled 3%–5% risk per trade.
   - The `why_now` rationale must display the contraction sequence (e.g. `3T VCP (18.2% → 9.4% → 3.8%)`), VDU confirmation (`VDU ✓`), distance to the pivot breakout level, and trade risk %.
