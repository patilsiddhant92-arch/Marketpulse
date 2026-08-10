# MarketPulse recovery release checklist

Do not promote the recovery branch or change the production default until every required gate below has evidence.

## Data and pipeline

- [ ] Back up both market and user DuckDB files; record file sizes/checksums.
- [ ] Run the recovery audit and record market date, candidate date, score versions, portfolio count, and PR counts.
- [ ] Validate a complete session, duplicate session, partial session, checksum change, and date gap.
- [ ] Confirm the PR ZIP remains in the session manifest and report row counts are durable and idempotent.
- [ ] Confirm `focused-v2` is materialized for exactly the accepted market date.
- [ ] Confirm Data Health fails visibly for a missing, stale, or mismatched decision snapshot.

## Decision quality

- [ ] Confirm eligible rows are hard-gated at market cap ≥ ₹1,000 Cr; missing cap is blocked, never treated as zero or a warning.
- [ ] Confirm missing stop/support/pivot geometry cannot become `Prepare`.
- [ ] Review the read-only focused-v1 versus focused-v2 comparison: overlap, rejected symbols/reasons, rank changes, score distributions, and resolved 5/10/20/60-session outcomes where available.
- [ ] Review at least 20 resolved sessions, or all available sessions when fewer exist, before adopting a new score policy.

## User data and UI

- [ ] Migrate legacy portfolio/journal/event rows once, with a backup and row-count/checksum record.
- [ ] Confirm Add/Edit/Sell/Reopen/Delete write only to the user database and every mutation creates an event.
- [ ] Confirm new positions require entry, stop, target, thesis, and invalidation context.
- [ ] In Chrome, verify all seven destinations: Today, Candidates, Sector Intel, Momentum, Deals, Portfolio, and Data Health.
- [ ] Verify desktop and 390px layouts, no page-level horizontal overflow, working portfolio actions, and no application console errors.

## Rollback

If any gate fails, keep the legacy production UI/default, restore the backed-up market database, retain the user database, and investigate from the branch. The recovery UI is not a substitute for an accepted EOD snapshot.
