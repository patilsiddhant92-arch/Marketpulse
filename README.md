# MarketPulse

MarketPulse is an NSE end-of-day decision desk for swing traders. It separates three concerns that must not be mixed:

- **Market data**: NSE daily prices, enrichment, breadth, sector rotation, bulk/block deals, and PR reports.
- **Audited decisions**: a versioned `focused-v2` snapshot with explicit market-cap, liquidity, price-band, geometry, trigger-distance, and reward-to-risk gates.
- **User data**: portfolio positions, thesis/invalidation notes, risk geometry, journal entries, and event history in `Database/marketpulse_user.duckdb`.

## Run locally

```powershell
.\Launch_MarketPulse.bat
```

The UI binds to `127.0.0.1:8081` by default so it does not collide with other local apps using port 8080. Set `MP_PORT` (preferred), `PORT`, `MP_HOST`, `MP_DB_PATH`, or `MP_USER_DB_PATH` for another environment. The normal UI reads the market database **read-only** and writes portfolio/journal only to `Database/marketpulse_user.duckdb`. EOD market writes happen through `Scripts/daily_pipeline.py`.

**Hosting:** leave `MP_HOST` unset (loopback). Binding to `0.0.0.0` or any non-loopback host requires `MP_ALLOW_REMOTE=1`. There is **no authentication** — do not expose the UI on a public network.

## Decision workflow

1. Run `Run_MarketPulse_Auto.bat` after the NSE session.
2. Open **Data Health** and confirm the market date and `focused-v2` decision date match.
3. Use **Today** for the short audited queue and **Candidates** for blocked diagnostics and filters.
4. Before entering a trade, record entry, stop, target, thesis, and invalidation in **Portfolio**.
5. Use the score comparison tool before changing a policy or promoting a new score version.

The system is research support, not an execution system or a guarantee of returns. Validate every candidate on a chart and apply your own risk limits.

## Recovery branch evidence

The recovery design, implementation plan, baseline audit, and release gates live under `docs/`. The production default should not switch to `focused-v2` until the release checklist is complete and the shadow comparison has been reviewed.
