"""Canonical Action Desk contract: flags, pool, queues, Darvas constants, exposure gate.

Playbook, Info tab, and Action Desk labels compile from this module.
Do not duplicate thresholds or instructional copy in UI files.
"""
from __future__ import annotations

import os
from typing import Any, Mapping


def flag_on(name: str, *, default: bool = False) -> bool:
    """Env truthy/falsey with an explicit default when unset/blank.

    Truthy: 1/true/yes/on. Falsy: 0/false/no/off. Anything else falls back to default.
    """
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


# MP_SECTOR_V2 and MP_DARVAS_V2 default ON; MP_DARVAS_WEEKLY stays off.
# Opt out with MP_SECTOR_V2=0 / MP_DARVAS_V2=0. No collision with MP_LEGACY_PAGES / MP_DEFAULT_TAB.

POOL = dict(min_mcap=1000.0, min_adv_cr=3.0, min_band=5.0)

QUEUE_DISPLAY_CAPS = dict(
    darvas=40,  # display window; button shows unclipped count
    darvas_10ema=40,
    vcp=40,
)

# Single source of truth for Darvas/squeeze knobs. Imported by Scripts.darvas_squeeze.
DARVAS = dict(
    max_squeeze_pct=5.0,
    max_range_pct=4.0,
    max_rvol=1.0,  # Approach A: dry/shallow volume hard gate (kills MAXHEALTH-class wet coils)
    ceiling_tol=1.002,
    wick_floor_tol=0.995,
    close_floor_tol=0.998,
    undercut_cap_tol=0.985,
    ema_stack_tol=0.004,
    ema_trend_tol=0.995,
    box_lookback_sessions=252,
    display_window=40,
)

SECTOR_DEFAULT_SORT = "turnover_share_delta_5d"  # DESC
SECTOR_DEFAULT_LEVEL = "Broad Industry"  # board only; query_sector_rotation_overview default stays "Sector"

ACTION_DESK_SUBTITLE = (
    "Executive swing trading command center: Exposure gate, leading themes, "
    "Darvas Squeeze + Darvas 10 EMA + VCP only."
)

# AD exposes exactly three queues. Retired screeners are deleted, not demoted.
QUEUE_META = {
    "darvas": {
        "title": "1. Darvas Squeeze",
        "short_title": "1. Darvas Squeeze",
        "desc": (
            "Dry coil under TopBox into a rising 10 EMA (tightening Top-EMA, rvol <= 1.0). "
            "Approach A primary."
        ),
        "tv_key": "darvas",
        "cap_key": "darvas",
        "tier": "primary",
    },
    "darvas_10ema": {
        "title": "2. Darvas 10 EMA",
        "short_title": "2. Darvas 10 EMA",
        "desc": (
            "Post-thrust dry setups: Pullback (price to rising 10 EMA) or Catch-up "
            "(10 EMA rises into held highs). Approach A primary."
        ),
        "tv_key": "darvas_10ema",
        "cap_key": "darvas_10ema",
        "tier": "primary",
    },
    "vcp": {
        "title": "3. VCP",
        "short_title": "3. VCP",
        "desc": (
            "EMA shakeout reclaim with 3M force (>=+30%) and purple density "
            "(>=3 days |ret|>=5% on vol>=1M). Desk VCP v1 — fine-tune later."
        ),
        "tv_key": "vcp",
        "cap_key": "vcp",
        "tier": "primary",
    },
}

PRIMARY_QUEUES = ("darvas", "darvas_10ema", "vcp")
MORE_QUEUES = ()  # retired — kept empty so UI loops stay safe




def _when_aggressive(a: Mapping[str, Any]) -> bool:
    # Live action_desk.py branches: adv>=58, ab20>=48, ab200>=45, vix<15, no spike, no net lows.
    # Missing breadth % (None) skips the band — same honesty as missing VIX.
    if a.get("adv_pct") is None or a.get("ab20_pct") is None or a.get("ab200_pct") is None:
        return False
    return (
        a["adv_pct"] >= 58.0
        and a["ab20_pct"] >= 48.0
        and a["ab200_pct"] >= 45.0
        and a["vix"] is not None
        and a["vix"] < 15.0
        and not a["vix_spike"]
        and not a["net_lows_expanding"]
    )


def _when_constructive(a: Mapping[str, Any]) -> bool:
    if a.get("adv_pct") is None or a.get("ab20_pct") is None:
        return False
    return (
        a["adv_pct"] >= 45.0
        and a["ab20_pct"] >= 38.0
        and a["vix"] is not None
        and a["vix"] < 18.0
        and not (a["vix_spike"] and a["net_lows_expanding"])
    )


def _when_selective(a: Mapping[str, Any]) -> bool:
    if a.get("adv_pct") is None:
        return False
    return a["adv_pct"] >= 35.0 and a["vix"] is not None and a["vix"] < 22.0


def _when_risk_off(a: Mapping[str, Any]) -> bool:
    return True


# Exact four branches from action_desk.py:121-145. First match wins.
# If vix is None: do not match branches that require vix < X; fall through; surface "VIX n/a".
EXPOSURE_RULES = [
    dict(
        id="aggressive",
        pct="75% - 100%",
        state="Aggressive / Full Trend",
        badge="mp-badge-good",
        dot="🟢",
        when=_when_aggressive,
        when_label=(
            "Advance ≥58%, >20 EMA ≥48%, >200 EMA ≥45%, VIX <15, no VIX spike, net 52W highs ≥ lows"
        ),
        guidance=(
            "Broad market participation is strong and volatility is low (<15 VIX). "
            "Deploy normal swing size (10-15% per position), use 3-5% stops, and let winning leaders compound."
        ),
    ),
    dict(
        id="constructive",
        pct="50% - 75%",
        state="Constructive / Selective",
        badge="mp-badge-good",
        dot="🟢",
        when=_when_constructive,
        when_label=(
            "Advance ≥45%, >20 EMA ≥38%, VIX <18, not (VIX spike AND net lows expanding)"
        ),
        guidance=(
            "Market is constructive but selective. Focus strictly on top relative strength leaders "
            "in leading sectors. Maintain normal 3-5% stops."
        ),
    ),
    dict(
        id="selective",
        pct="25% - 50%",
        state="Selective / Caution",
        badge="mp-badge-warn",
        dot="🟡",
        when=_when_selective,
        when_label="Advance ≥35%, VIX <22",
        guidance_net_lows=(
            "Net 52W Lows expanding ({count_52w_lows} lows vs {count_52w_highs} highs). "
            "Cut position sizes in half, take quick 2R profits, and trail stops tightly."
        ),
        guidance_vix_spike=(
            "VIX surge of +{vix_1d_pct:.1f}% indicates sudden volatility expansion. "
            "Avoid chasing breakouts; wait for calm base resets."
        ),
        guidance=(
            "Diverging market breadth. Cut position size in half, take quick partial profits "
            "at 2R to 3R, and trail stops tightly."
        ),
    ),
    dict(
        id="risk_off",
        pct="0% - 15%",
        state="Risk-Off / Defensive",
        badge="mp-badge-bad",
        dot="🔴",
        when=_when_risk_off,
        when_label="Any remaining tape, including missing VIX (shown as VIX n/a)",
        guidance=(
            "Net distribution, breadth breakdown, or high volatility. Protect capital in cash. "
            "Do not force new breakout buys until breadth recovers above 20 EMA."
        ),
    ),
]


def format_exposure_guidance(rule: Mapping[str, Any], args: Mapping[str, Any]) -> str:
    if rule["id"] == "selective":
        if args.get("net_lows_expanding"):
            return str(rule["guidance_net_lows"]).format(
                count_52w_lows=args.get("count_52w_lows", 0),
                count_52w_highs=args.get("count_52w_highs", 0),
            )
        if args.get("vix_spike"):
            return str(rule["guidance_vix_spike"]).format(
                vix_1d_pct=float(args.get("vix_1d_pct") or 0.0),
            )
    return str(rule["guidance"])


def exposure_playbook_line(rule: Mapping[str, Any]) -> str:
    dot = str(rule.get("dot") or "").strip()
    prefix = f"{dot} " if dot else ""
    return (
        f"{prefix}{rule['pct']} ({rule['state']}): {rule['when_label']}. {rule['guidance']}"
    )



def brief_fields_from_gate(gate: Mapping[str, Any]) -> dict[str, Any]:
    """Brief posture copy compiled from the Action Desk exposure gate (Overview tab retired).

    Allocation band and stance are the gate's own pct/state — never a second formula.
    Cash stance is the complement of the exposure band for Brief display only.
    """
    gid = str(gate.get("id") or "risk_off")
    cash_by_id = {
        "aggressive": "0% – 25% Cash",
        "constructive": "25% – 50% Cash",
        "selective": "50% – 75% Cash",
        "risk_off": "85% – 100% Cash",
    }
    tone_by_id = {
        "aggressive": "positive",
        "constructive": "info",
        "selective": "warning",
        "risk_off": "negative",
    }
    pct = str(gate.get("pct") or "")
    state = str(gate.get("state") or gid)
    return {
        "exposure_id": gid,
        "exposure_pct": pct,
        "exposure_state": state,
        "posture_title": f"{state} ({pct} Allocation)",
        "cash_recommendation": cash_by_id.get(gid, "85% – 100% Cash"),
        "posture_desc": str(gate.get("guidance") or ""),
        "regime_tone": tone_by_id.get(gid, "negative"),
    }


def match_exposure(args: Mapping[str, Any]) -> dict[str, Any]:
    """First matching EXPOSURE_RULES entry wins.

    Branches that require vix < X do not match when vix is None; they fall through.
    """
    matched = EXPOSURE_RULES[-1]
    for rule in EXPOSURE_RULES:
        if rule["when"](args):
            matched = rule
            break
    vix = args.get("vix")
    vix_na = vix is None
    return {
        "id": matched["id"],
        "pct": matched["pct"],
        "state": matched["state"],
        "badge": matched["badge"],
        "guidance": format_exposure_guidance(matched, args),
        "vix_na": vix_na,
        "vix_label": "VIX n/a" if vix_na else None,
    }


PLAYBOOK = {
    "modal_title": "ACTION DESK FIELD GUIDE & TRADING PLAYBOOK",
    "tab_flow": "1. 3-Step Workflow",
    "tab_cols": "2. How to Read Data",
    "tab_holy": "3. Holy Trinity Checklist",
    "tab_cases": "4. Case Studies (MVGJL/XTRANET)",
    "tab_routine": "5. 15-Min Daily Routine",
    "workflow_intro": "Never buy stocks in isolation. Always execute in this 3-step sequence:",
    "step1_title": "STEP 1: THE EXPOSURE GATE (Market Breadth)",
    "step1_intro": (
        "Look at the top-left card before reviewing any stocks. "
        "These four bands are the live Exposure Gate (first match wins):"
    ),
    "step2_title": "STEP 2: LEADING SECTOR THEMES (Industry Momentum)",
    "step2_intro": (
        "Prefer setups from the sectors currently listed as leaders on Action Desk Step 2. "
        "Isolated names in lagging groups are lower priority."
    ),
    "step2_bullets": [
        "Pick setups from the #1, #2, or #3 sectors shown on Action Desk Step 2.",
        "Avoid isolated 'lone-wolf' stocks in dead or lagging sectors.",
    ],
    "step3_title": "STEP 3: SETUP QUEUES (8 queues — choose your strategy)",
    "step3_bullets": [
        "PRE-MOVE ACCUMULATION: use Silent Coil, Stair-Step, or Darvas Squeeze near 10 EMA before expansion.",
        "CONTINUATION: use Spike-Pause to catch high-tight flags after an initial 10%+ thrust.",
        (
            "NEAR PIVOT / BREAKOUTS: use Near 20D Pivot, EMA Pullback, or 52W Breakouts for Stage 2 leaders. "
            "Queue 1 is a 20-day high proximity scan, not Minervini VCP."
        ),
    ],
    "metrics_intro": "Metrics Cheatsheet: What Every Column Means & What to Look For",
    "holy_title": "The 'Holy Trinity' Checklist: DNA of a 10% / 20% UC Super-Mover",
    "holy_sub": (
        "Before entering any stock, verify these 3 desk filters. "
        "They are execution checks, not verified hit rates."
    ),
    "cases_intro": "Empirical Case Studies: Exactly What Winners Looked Like Before The Move",
    "info_header": "Action Desk Trading Playbook & Decision Framework",
    "info_sub": (
        "3-step funnel, data dictionary, Holy Trinity checklist, and case studies. "
        "Exposure bands and queue labels compile from desk_contract."
    ),
    "close_label": "Close Playbook",
    "open_modal_label": "📖 Open Interactive Modal ↗",
    "open_full_label": "📖 Open Full Playbook",
    "field_guide_fallback": (
        "Pro Tip: Filter for stocks sitting within ±1.5% of 10 EMA with institutional ticket expansion (🏛️)."
    ),
}

METRICS_CHEATSHEET = [
    (
        "TICKET 🏛️",
        "Institutional Order Size",
        "avg_trade_size / 20D avg. Large institutions place block orders that small retail cannot.",
        "Look for 1.3x 🏛️ to 2.2x 🏛️. Avoid <0.8x.",
    ),
    (
        "BAND",
        "Circuit Limit Collar",
        "Daily price band limit (10% vs 20%).",
        (
            "10% ⚡ can starve supply and roll unfilled demand to the next session. "
            "Treat as a qualitative edge, not a measured hit rate."
        ),
    ),
    (
        "10 EMA %",
        "Support Proximity",
        "Distance from current price to the rising 10-day exponential moving average.",
        "Target [-1.5%, +1.5%]. Never chase if > +6.0% extended from 10 EMA.",
    ),
    (
        "RVOL TRAIL",
        "7-Day Volume Story",
        "Multi-day relative volume progression (e.g. 0.4x -> 0.3x -> 0.2x).",
        "Drying up (VDU) OR stair-stepping higher (0.5x -> 1.0x -> 1.8x). Avoid sudden 9x exhaustion churn.",
    ),
    (
        "DELIV %",
        "Delivery Percentage",
        "Percentage of traded shares taken as delivery into demat accounts.",
        "Target >= 50% to 70% (real absorption). Blast days with <15% delivery are churn risk.",
    ),
    (
        "DEAL FLOW",
        "Institutional Deals",
        "Large block/bulk deals reported to exchange in the last 25 sessions.",
        "Look for '🏛️ +₹50Cr' tags confirming institutional buying.",
    ),
    (
        "CMP / TRIGGER",
        "Execution Price",
        "Current market price vs breakout trigger level.",
        "Buy at CMP near 10 EMA support or on breakout through trigger price.",
    ),
]

HOLY_TRINITY = [
    {
        "title": "SUPPORT PROXIMITY (Unextended Near 10 or 20 EMA)",
        "body": (
            "Price must be within [-1.5%, +2.5%] of the 10 EMA or 20 EMA. "
            "Silent Coil uses abs(away_10ema) ≤ 2.5 or abs(away_20ema) ≤ 2.5. "
            "Never chase a stock already 8% away from its moving average."
        ),
    },
    {
        "title": "VOLUME SIGNATURE (Severe VDU or Stair-Step)",
        "body": (
            "Either RVOL is completely dry (<= 0.70x) showing zero selling pressure, "
            "OR RVOL is stair-stepping higher (0.6x -> 1.1x -> 1.8x) into a tight range "
            "showing stealth accumulation."
        ),
    },
    {
        "title": "INSTITUTIONAL FOOTPRINT (Ticket Size Expansion 🏛️ OR High Delivery >=50%)",
        "body": (
            "Large orders leave footprints. Look for the '🏛️' ticket expansion badge (>=1.2x) "
            "and delivery >= 50%. This separates real institutional accumulation from retail churn."
        ),
    },
]

HOLY_BONUS = (
    "BONUS EDGE: 10% Band (marked 10% ⚡) can roll demand into the next session via supply starvation. "
    "Qualitative only — no verified runner rate."
)

SWING_CASE_STUDIES = [
    {
        "title": "CASE 1: MVGJL — From ₹151 to ₹215.88 (+43% in 5 Days, 20% UC)",
        "tone": "text-amber-400",
        "bullets": [
            "• Day -1 (Aug 31): Price ₹151.03, sitting -1.47% on 10 EMA support.",
            "• Volume & Delivery: RVOL was 0.67x (VDU), Delivery was 61.11% (Massive institutional absorption).",
            "• Ticket Size: 1.32x 🏛️ institutional order expansion.",
            "• 52W High Distance: -29.68% (Emerging Stage 1 base turnaround).",
            "• Outcome: Surged +7.5% next day on 6.7x RVOL -> paused 2 days at 10 EMA -> locked 20.00% UPPER CIRCUIT!",
        ],
    },
    {
        "title": "CASE 2: XTRANET — Three Consecutive 20% Upper Circuits",
        "tone": "text-sky-400",
        "bullets": [
            "• Day -1 (Aug 26): Resting at ₹159.83, sitting -0.41% right on 10 EMA.",
            "• Volume & Delivery: RVOL dried up to 0.37x (Extreme VDU), Delivery was 48.31%.",
            "• 200 EMA status: Newer stock with no 200 EMA (would be blocked by old screener, caught by new screener).",
            "• Outcome: Exploded 20.00% Upper Circuit on Day 2 -> paused at 10 EMA (0.38x RVOL) -> hit two more 20% Upper Circuits!",
        ],
    },
    {
        "title": "CASE 3: COMSYN & HDBFS (Current Real-Time Setups)",
        "tone": "text-emerald-400",
        "bullets": [
            "• COMSYN: 1.6x 🏛️ ticket size, 10% ⚡ supply-starvation band, +0.0% on 10 EMA, 0.56x RVOL, 50.8% delivery.",
            "• HDBFS: 2.2x 🏛️ ticket size, +0.1% on 10 EMA, 1.96x stair-step RVOL, 85.8% delivery (extreme block buying).",
        ],
    },
]

ROUTINE_WINDOWS = ("15:45", "08:30")
ROUTINE_HEADLINE = (
    "Your 15-Minute Checklist (15:45 after the close, 08:30 before the open)"
)
ROUTINE_STEPS = [
    (
        "Minute 1-2",
        "Check Exposure Gate",
        "Look at Step 1 card. If Green/Yellow, proceed. If Red, halt new trades and protect existing positions.",
    ),
    (
        "Minute 3-5",
        "Review Leading Sectors",
        "Note which sectors are in the top 3. Setups in these sectors have highest follow-through.",
    ),
    (
        "Minute 6-10",
        "Scan Darvas Squeeze, 10 EMA, and VCP",
        "Work the three primary queues. Look for rows displaying the '🏛️' ticket expansion badge and '10% ⚡' band.",
    ),
    (
        "Minute 11-13",
        "Inspect the Top 3 Charts",
        "Click on candidate rows. Verify in the right-pane chart that candles are orderly (tight horizontal bars, not wild wicks) and hugging the white 10 EMA line.",
    ),
    (
        "Minute 14-15",
        "Copy to TradingView",
        "Click '📋 Copy [Queue] (TV)' to paste into your TradingView watchlist and set GTT trigger orders near the 10 EMA or at trigger price.",
    ),
]

FIELD_GUIDE_TIPS = {
    "darvas": (
        f"Darvas Squeeze Field Guide: Price is compressed inside the top {DARVAS['max_squeeze_pct']:.1f}% "
        f"of the Darvas box with rising 10/20 EMA support. Look for squeeze_pct <= {DARVAS['max_squeeze_pct']:.1f}% "
        f"and candle range <= {DARVAS['max_range_pct']:.1f}%."
    ),
    "darvas_10ema": (
        "Darvas 10 EMA Field Guide: Post-thrust dry Pullback (price to rising 10 EMA) or Catch-up "
        "(10 EMA rises into held highs). Wick tests OK if close stays constructive."
    ),
    "vcp": (
        "VCP Field Guide (v1): EMA shakeout reclaim + raw 3M >= +30% + purple density "
        "(>=3 days |ret|>=5% on vol>=1M). Fine-tune contraction geometry later."
    ),
}


def _walk_strings(value: Any, out: list[str]) -> None:
    if isinstance(value, str):
        if value:
            out.append(value)
        return
    if callable(value):
        return
    if isinstance(value, Mapping):
        for item in value.values():
            _walk_strings(item, out)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _walk_strings(item, out)


def iter_playbook_copy() -> list[str]:
    """All user-visible strings the playbook / Info trading guide may show."""
    out: list[str] = []
    _walk_strings(PLAYBOOK, out)
    _walk_strings(QUEUE_META, out)
    _walk_strings(METRICS_CHEATSHEET, out)
    _walk_strings(HOLY_TRINITY, out)
    _walk_strings(HOLY_BONUS, out)
    _walk_strings(SWING_CASE_STUDIES, out)
    _walk_strings(ROUTINE_HEADLINE, out)
    _walk_strings(ROUTINE_STEPS, out)
    _walk_strings(ROUTINE_WINDOWS, out)
    _walk_strings(FIELD_GUIDE_TIPS, out)
    _walk_strings(ACTION_DESK_SUBTITLE, out)
    for rule in EXPOSURE_RULES:
        _walk_strings(
            {k: v for k, v in rule.items() if k != "when"},
            out,
        )
        out.append(exposure_playbook_line(rule))
    out.append("VIX n/a")
    return out


__all__ = [
    "flag_on",
    "POOL",
    "QUEUE_DISPLAY_CAPS",
    "DARVAS",
    "SECTOR_DEFAULT_SORT",
    "SECTOR_DEFAULT_LEVEL",
    "ACTION_DESK_SUBTITLE",
    "QUEUE_META",
    "PRIMARY_QUEUES",
    "MORE_QUEUES",
    "EXPOSURE_RULES",
    "match_exposure",
    "format_exposure_guidance",
    "exposure_playbook_line",
    "PLAYBOOK",
    "METRICS_CHEATSHEET",
    "HOLY_TRINITY",
    "HOLY_BONUS",
    "SWING_CASE_STUDIES",
    "ROUTINE_WINDOWS",
    "ROUTINE_HEADLINE",
    "ROUTINE_STEPS",
    "FIELD_GUIDE_TIPS",
    "iter_playbook_copy",
]
