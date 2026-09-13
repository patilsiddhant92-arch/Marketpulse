# MarketPulse Morning / Lab / Ops Redesign

**Date:** 2026-09-13  
**Status:** Design locked from live Chrome pass (EOD 2026-09-11) + UI Desk review  
**App:** MarketPulse2.0 (`D:\Sid\MarketPulse2.0`)  
**Audience:** traders first; agents implement next  

---

## 1. Why this doc exists

P0 honesty is done (UC claims stripped, Darvas one-truth, pre-move queues owned by Action Desk). Live UI still fights itself:

- Two exposure/posture authorities on the same EOD
- Market Health reprinted as a fat 7-card deck on Action Desk **and** Momentum
- Ten equal-weight primary tabs; peers and sector Δ SHARE orphaned from the decide surface
- Charts siloed (Stock 360 EMA/Darvas ≠ Trends breadth history)

This redesign defines **information architecture and honesty rules** before code. No tab rename theater until the honesty stitch lands.

---

## 2. Evidence (EOD 2026-09-11 live)

| Surface | What the pixels show | Verdict |
|---|---|---|
| **Action Desk** | Index tape, EOD OK, Market Health Weakening + 7 cards, themes, STEP1 exposure **25–50% · Selective/Caution**, 8 queues, Stock 360 rail (candles + 10/20/50/200 EMA + Darvas) | Already Morning — keep as default land |
| **Overview** | Regime “Defensive Consolidation”, posture **25–40% allocation**, **60–75% cash**, footer TACTICAL ACTION PLAN repeats cash | Competing briefing — honesty bug |
| **Momentum** | Dense EMA/SMA filter board; full Health deck again; “HIDE MARKET HEALTH” admits noise | Lab — health default off |
| **Template** | Minervini SMA checklist + results; chip language like `Fin #12` | Lab — keep |
| **Market Trends** | Breadth/liquidity history charts (e.g. trailing 180 sessions) | Lab — chart-kit unify later |
| **Sectors** | Δ SHARE 5D cards, grain toggles, state badges, classification tree | Full destination — **not** a drawer |
| **Deals** | 3-tier Institutional Desk + TV exports (Conviction / Fresh Whale / Prop HFT / Quarantine) | Heavy Ops destination — **not** a drawer |
| **Watchlists** | Thin (WL1 = 2 names) | Demote under Ops |
| **Portfolio** | Risk desk with **MISSING STOPS: 5** | Ops gold — optional Morning attention chip |
| **Info** | Macro/swing playbooks + system health | Ops / reference |

Artifacts: `_ui_audit/` screenshots from Chrome DevTools Protocol (Chrome MCP connector not exposing tools in Grok Bot; CDP used instead).

---

## 3. Design principles

1. **One job per mode** — Morning decides; Lab explores; Ops manages.
2. **One number authority** — exposure/posture has a single owner (`desk_contract` / Action Desk). No second formula on Overview/Brief.
3. **One Health surface** — severity pill (or one strip) in global/Morning chrome; scanners do not reprint the 7-card deck by default.
4. **Stitch, don’t amputate** — Sectors and Deals stay pages; surface their signals *into* AD where useful.
5. **Reuse chip grammar** — peer/sector language already exists (`Fin #12`, `CapGoods #4`, `Health #1`). Extend it; don’t invent a new visual language.
6. **Density budget** — AD matrix / STEP2 row stays ~**1–1.5 lines**. If peer + Δ SHARE wraps, move to right-rail / hover.
7. **No rename theater** — change weight and ownership first; Morning/Lab/Ops *labels* only after P1 honesty.

---

## 4. Ranked keep / cut / merge

### KEEP
1. Action Desk as default Morning (gate, themes, 8 queues, Stock 360)
2. Sectors as full Δ SHARE destination
3. Deals 3-tier Institutional Desk + exports
4. Momentum + Template as Lab boards
5. Portfolio risk desk (MISSING STOPS)
6. Index tape + EOD OK + Quick Search as global chrome
7. Existing sector/rank chip language on Template & Watchlists

### CUT (this build or immediately after)
1. Overview’s independent posture (25–40% / 60–75% cash + competing TACTICAL ACTION PLAN)
2. Full 7-card Market Health reprint on Momentum (and Overview breadth restatement as a second deck)
3. Equal visual weight across all 10 primaries
4. Watchlists as equal primary (demote)

### MERGE / STITCH
1. Overview → Morning **Brief** that *reads* AD’s gate (one owner)
2. Market Health → one Morning pill/strip; Momentum health default collapsed/off
3. Peer-rank chip + group Δ SHARE → AD matrix / STEP2 (reuse chip grammar)
4. Sectors stays a page; Δ SHARE also surfaces on AD STEP2
5. Chart 20 / 65 / 252 kit — **P2** merge of Stock 360 + Trends (do not block P1)

---

## 5. Concrete wire (weight + grouping, not rename yet)

### 5.1 Morning — decide today (default land: Action Desk)

| Slot | Surface | Role |
|---|---|---|
| Primary | **Action Desk** | Gate owner, Health pill, themes, queues, Stock 360 |
| Secondary | **Brief** (ex-Overview) | Narrative only; mirrors AD numbers; no second gate |
| Secondary | **Sectors** | Full Δ SHARE destination; linked from STEP2 |

**Global shell:** index tape · EOD OK · Health pill (severity) · Quick Search  
**Optional:** Morning attention chip → Portfolio when `MISSING STOPS > 0`

### 5.2 Lab — explore / prep

| Surface | Role |
|---|---|
| **Momentum** | Dense filter board — label filters **Lab only** |
| **Template** | Minervini SMA lab |
| **Market Trends** | Breadth / history charts (shared chart kit later) |

UC Thrust remains lab-only (already honesty-stripped in P0). No new production UC screener until lift research graduates.

### 5.3 Ops — manage / research destinations

| Surface | Role |
|---|---|
| **Deals** | Institutional 3-tier + exports |
| **Portfolio** | Positions + risk desk |
| **Watchlists** | Thin personal lists (demoted) |
| **Info** | Macro / swing playbooks + system & data health |

### 5.4 Nav treatment after P1 honesty

- Morning group visually louder (AD default, Brief + Sectors nearby)
- Lab + Ops quieter secondary grouping
- Full label rename to “Morning / Lab / Ops” **only after** stitch lands and one live trader walkthrough confirms

---

## 6. Build phases

### P1 — Morning honesty stitch (this sprint)

**Order is load-bearing (UI Desk):**

#### P1.1 — One exposure / posture owner
- **Owner:** Action Desk STEP1 / `Scripts.desk_contract` exposure gate
- **Overview/Brief:** consume the same struct (band, stance label, cash implication if any). Exact same numbers in UI copy. No second yellow posture box with a different band.
- **Acceptance:** same EOD → AD and Brief show identical exposure band + stance; grep/tests prove Overview does not hardcode a competing band
- **Likely files:** `Scripts/desk_contract.py`, `App/pages/action_desk.py`, `App/pages/overview.py`, tests under `tests/test_action_desk.py` (+ new Overview contract test)

#### P1.2 — One Health surface
- Extract / promote a single Health pill (severity severity: Weakening / etc.) for global or AD top chrome
- Momentum: Market Health **default off** (keep “HIDE” / collapse; prefer default collapsed)
- Overview/Brief: cite the pill; do not reprint the 7-card deck
- **Acceptance:** live Momentum open shows no 7-card deck by default; AD retains decide-context Health; numbers still one-sourced from market health read model
- **Likely files:** `App/ui/market_health.py`, `App/app.py` / page mounts, `App/pages/action_desk.py`, Momentum path in `App/app.py` or screener mount

#### P1.3 — Peer-rank + group Δ SHARE on AD
- On AD matrix / STEP2: peer-rank chip + group Δ SHARE using existing chip grammar (`CapGoods #4` style)
- Density rule: row ≤ ~1.5 lines; else right-rail / hover strip
- Link STEP2 → Sectors page for deep drill (do not drawer-amputate Sectors)
- **Acceptance:** from a queue row, peer rank + Δ SHARE visible without opening Stock 360; opening Stock 360 still works
- **Likely files:** `App/pages/action_desk.py`, `App/ui/columns.py`, sector read model / `App/pages/research/sector_board.py` (read-only reuse), Stock drawer only if rail fallback

#### P1.4 — Nav weight demote (after 1–3)
- Visual grouping / quieter Lab+Ops tabs; Overview loses primary-cockpit parity (Brief secondary)
- Watchlists demoted in visual weight
- Still no hard rename unless product walkthrough asks for it

### P2 — Shared chart kit (after P1)
- One ECharts kit: ranges **20 / 65 / 252** (sessions), shared brush + legend density
- Stock 360 and Trends consume the kit; no one-off snowflake ranges
- Darvas / EMA overlays remain AD/Stock 360 concerns but sit on the shared base

### Later leftovers (explicitly out of P1)
- Badge / hide Market Trends windows that exceed honest history (index_daily ~52 sessions vs breadth_daily ~585)
- Template SMA-only clarity (already mostly true)
- Promote Data Health out of Info burying
- Deals default filter honesty (HFT vs institutional)
- UC lab §2 / §3 research (no production screener until lift)
- Cut orphan `sector_intel` / legacy sector paths
- Full Morning/Lab/Ops label rename

---

## 7. Honesty contract (non-negotiable)

| Claim | Owner | Rule |
|---|---|---|
| Exposure band + stance | `desk_contract` → Action Desk | Single writer; Brief mirrors |
| Market Health severity + 7 metrics | market health read model | One render path preferred; Momentum does not auto-show deck |
| Queue ownership (Silent Coil / Stair-Step / Spike-Pause) | Action Desk queues 6–8 | Momentum must not re-list (P0 done) |
| Darvas knobs | `desk_contract.DARVAS` | Single owner (P0 done) |
| UC Thrust | Lab only | No “backtested / empirical” claims (P0 done) |
| Sector Δ SHARE | sector board / metrics | AD STEP2 may *display*; Sectors remains source UI for drill |

---

## 8. What would change this design

| Signal | Response |
|---|---|
| Trader hop counts show Overview used as decide surface | Brief stays primary-weight; still must mirror AD gate |
| Deals used as morning scan | Promote Deals toward Morning secondary (still not a drawer) |
| Peer path already primary elsewhere | Drop in-matrix peer chip; keep rail |
| Peer + Δ SHARE forces wrap / tooltip hell | Right-rail / hover only |
| Lab tools *are* the morning scan | Merge Lab-into-Morning instead of demoting Lab |

None of these showed in the 2026-09-11 shot pass.

---

## 9. Non-goals (this redesign)

- Rewriting NiceGUI chrome for aesthetics alone
- Collapsing Sectors or Deals into drawers
- Shipping a production UC pre-limit screener
- Full tab label rename before P1 honesty
- Unifying chart kit before exposure/Health honesty

---

## 10. Implementation handoff

When greenlit to code:

1. Implement **P1.1 → P1.2 → P1.3 → P1.4** in that order (TDD where contracts exist: exposure struct equality, health default-off, chip column presence).
2. Re-verify with Chrome CDP screenshots of AD, Brief/Overview, Momentum.
3. Only then open P2 chart-kit plan.
4. Optional companion implementation plan: `docs/superpowers/plans/2026-09-13-morning-honesty-stitch.md` (task-level checkboxes) — write when coding starts, not before.

**Success for this doc:** a trader (or agent) can read §5–§6 and know what Morning vs Lab vs Ops means, what not to build yet, and the exact honesty bugs to kill first.

---

## 11. References

- Live screens: `D:\Sid\MarketPulse2.0\_ui_audit\` (and staged copies under agent-tools)
- Prior audit: `docs/MARKETPULSE-AUDIT-AND-UPGRADE-DESIGN.md`
- All-builds plan: `docs/superpowers/plans/2026-09-12-marketpulse-all-builds.md`
- UC lift: `docs/research/2026-09-12-uc-lift-summary.md`
- UI Desk ranked review (2026-09-13): keep/cut/merge + wire adopted into this doc
