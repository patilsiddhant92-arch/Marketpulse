"""Next-Gen Tech Thematic Read Model — AI, Data Centers, Semiconductors, and Physical Ancillaries."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import duckdb
import numpy as np
import pandas as pd


NEXTGEN_TECH_UNIVERSE: dict[str, dict[str, str]] = {
    "Silicon & Chip Design": {
        "MOSCHIP": "ASIC & Chip Design / Semiconductor IP (DLI Scheme)",
        "CGPOWER": "OSAT / ATMP Mega Packaging Fab (Sanand, Gujarat - JV with Renesas)",
        "KAYNES": "OSAT / ATMP Packaging Facility & High-Density Interconnect PCBs",
        "TATAELXSI": "Automotive Semiconductor Architecture, VLSI & Edge AI Silicon",
        "DIXON": "High-End Electronic Manufacturing Services (EMS) & Server Assembly",
        "CYIENTDLM": "Electronic Manufacturing Services (EMS) for Semiconductor Test Gear",
        "CYIENT": "Design-Led Semiconductor & VLSI Engineering Services",
        "SYRMA": "Precision EMS, RFID & Power Module Assemblies",
        "AVALON": "Clean-Room Box-Build EMS & Aerospace Electronics",
        "AETHER": "Specialty Chemical Precursors for Semiconductor Lithography",
        "TATATECH": "Embedded Silicon & Connected Vehicle Engineering",
    },
    "Compute & AI Servers": {
        "NETWEB": "AI Cloud Supercomputing Servers & GPU Racks (Official Nvidia OEM Partner)",
        "E2E": "Accelerated Cloud GPU Compute Infrastructure (Nvidia Cloud Partner)",
        "BBOX": "Hyperscale Data Center System Integration & Structured Networking",
        "TATACOMM": "Subsea Global Fiber Interconnects & Cloud GPU-as-a-Service",
        "BHARTIARTL": "Hyperscale Green Data Center Operator (Nxtra Data Centers - 400MW+)",
        "ANANTRAJ": "Pure-Play Data Center Infrastructure Developer (320-Acre NCR Campuses)",
        "ADANIENT": "Hyperscale Data Center Campus Developer (AdaniConneX JV - 1GW+)",
        "RELIANCE": "Jio Hyper-Scale Data Centers & AI Cloud Infrastructure",
        "RAILTEL": "Pan-India Optical Fiber Backbone & Edge Data Center Colocation",
    },
    "Heavy Power & Transformers": {
        "ABB": "Heavy Electrification, Substation Switchgears & Power Quality",
        "SIEMENS": "Data Center Electrification, Smart Substations & Automation",
        "POWERINDIA": "Hitachi Energy - High Voltage Grid Interconnections & HVDC",
        "GVT&D": "GE Vernova T&D - Power Transmission & Grid Automation",
        "SCHNEIDER": "Medium-Voltage Switchgear, Smart Power Distribution & UPS",
        "TARIL": "Transformers & Rectifiers - High-Capacity Utility Transformers",
        "VOLTAMP": "Dry-Type & Oil-Filled Step-Down Substation Transformers",
        "SHILCTECH": "Renewable & Heavy Power Distribution Transformers",
    },
    "Cables & Optical Fiber": {
        "POLYCAB": "Extra High Voltage (EHV) Power Cabling & Optical Fiber",
        "KEI": "EHV Power Transmission Cables & Data Center Cabling",
        "APARINDS": "Specialized Conductor Cables & Transformer Insulating Oils",
        "HAVELLS": "Industrial Power Cables, Switchgear & Distribution Panels",
        "FINCABLES": "Electrical Power & High-Speed Communication Cables",
        "RRKABEL": "Commercial & Industrial Fire-Resistant Power Cables",
        "STLTECH": "High-Density Optical Fiber Cables & Hyperscale Interconnects",
        "HFCL": "Optical Fiber Cables & High-Capacity Transmission Equipment",
    },
    "Cooling & Precision HVAC": {
        "KRN": "Precision Heat Exchangers & Liquid-Cooling Condenser Coils for Server Racks",
        "BLUESTARCO": "Data Center Precision Air Conditioning (PAC) & Hyperscale Chiller Plants",
        "VOLTAS": "Commercial Water-Cooled Chillers & Precision HVAC",
        "AMBER": "Industrial Thermal Solutions & Precision Cooling Modules (Sidwal)",
    },
    "Batteries & Backup Power": {
        "ARE&M": "Amara Raja - 16 GWh Lithium-Ion Cell Gigafactory & Industrial UPS Banks",
        "EXIDEIND": "Exide Industries - 12 GWh Lithium Cell Gigafactory & Lead-Acid UPS",
        "HBLENGINE": "Specialized Industrial Batteries (Ni-Cd/T-BESS) & Power Management",
        "CUMMINSIND": "Heavy-Duty Diesel Generator (DG) Sets for Zero-Downtime Backup Power",
        "KIRLOSENG": "Standby Industrial Power Generation & Diesel Engines",
    },
    "Pipes, Pumps & Water (ZLD)": {
        "ASTRAL": "CPVC Chilled-Water Closed Loops & BlazeMaster Fire Sprinkler Piping",
        "SUPREMEIND": "Industrial CPVC & Composite Piping Systems",
        "FINPIPE": "Industrial PVC/CPVC Plumbing & Chilled Water Lines",
        "PRINCEPIPE": "Industrial CPVC & Drainage Piping Systems",
        "KIRLOSBROS": "Centrifugal Pumps, Condenser Cooling Water & Firefighting Pump Sets",
        "KSB": "Precision Industrial Pumps & Valves for High-Pressure Cooling Circuits",
        "SHAKTIPUMP": "High-Efficiency Stainless Steel Booster & Circulation Pumps",
        "WPIL": "Large-Scale Centrifugal & Vertical Turbine Water Pumps",
        "WABAG": "VA Tech Wabag - Industrial Water Treatment, Desalination & ZLD Recycling",
        "THERMAX": "Industrial Absorption Chillers, Water Treatment & ZLD Systems",
        "IONEXCHANG": "Water Treatment Plants, Ion-Exchange Resins & Closed-Loop Filtration",
    },
    "Transformer Oils, BMS & AI Software": {
        "SOTL": "Savita Oil Tech - High-Grade Insulating Transformer Oils & Dielectric Fluids",
        "HONAUT": "Honeywell Automation - Integrated Building Management Systems (BMS)",
        "LT": "Larsen & Toubro - Turnkey Data Center Campus EPC & Modular Pods",
        "KPIL": "Kalpataru Projects - Civil & Electrical Power Substation EPC",
        "PERSISTENT": "Persistent Systems - GenAI LLM Deployment & Cloud-Native Engineering",
        "COFORGE": "Coforge - Autonomous Enterprise AI & Workflow Automation",
        "LTTS": "L&T Tech Services - Industrial AI, Robotics & Edge Computer Vision",
        "AFFLE": "Affle India - Consumer AI & Intent-Discovery Mobile Intelligence",
        "RATEGAIN": "RateGain - AI Dynamic Pricing & Demand Forecasting SaaS",
        "NEWGEN": "Newgen Software - AI-Powered Document Intelligence & Automation",
        "HAPPSTMNDS": "Happiest Minds - Dedicated Generative AI Business Unit",
        "LATENTVIEW": "Latent View Analytics - Pure-Play Enterprise Analytics & AI Consulting",
        "MAPMYINDIA": "MapmyIndia - Spatial AI, Autonomous Navigation & HD Mapping",
        "AURIONPRO": "Aurionpro Solutions - AI Transaction Processing & Digital Transit Tech",
    },
}


def get_all_thematic_symbols() -> list[str]:
    """Get the flat unique list of all thematic symbols."""
    syms = []
    for pillar in NEXTGEN_TECH_UNIVERSE.values():
        syms.extend(pillar.keys())
    return sorted(set(syms))


def get_symbol_thematic_metadata(symbol: str) -> tuple[str, str]:
    """Return (pillar_name, role_description) for a symbol."""
    for pillar_name, mapping in NEXTGEN_TECH_UNIVERSE.items():
        if symbol in mapping:
            return pillar_name, mapping[symbol]
    return "Next-Gen Tech", "Thematic Ecosystem Constituent"


def query_thematic_overview(db_path: Path) -> dict[str, Any]:
    """Aggregate momentum, breadth, and leadership metrics across all 8 thematic pillars."""
    db_path = Path(db_path)
    if not db_path.exists():
        return {"as_of": None, "pillars": [], "total_stocks": 0, "all_symbols": []}

    all_symbols = get_all_thematic_symbols()
    placeholders = ", ".join([repr(s) for s in all_symbols])

    with duckdb.connect(str(db_path), read_only=True) as db:
        # 1. Latest trade date
        max_d = db.execute("SELECT max(trade_date) FROM indicators_daily").fetchone()[0]
        if max_d is None:
            return {"as_of": None, "pillars": [], "total_stocks": 0, "all_symbols": all_symbols}

        as_of_str = str(pd.to_datetime(max_d).date())

        # 2. Fetch latest indicators for all thematic symbols
        sql = f"""
        SELECT i.symbol,
               coalesce(m.security_name, i.symbol) AS security_name,
               m.market_cap_cr,
               i.close_price,
               i.return_5d_pct,
               i.return_1m_pct,
               i.return_3m_pct,
               i.rs_percentile,
               coalesce(i.rvol, 1.0) AS rvol,
               i.delivery_pct,
               i.is_vcp,
               i.vcp_score,
               i.vcp_state,
               i.away_52w_high_pct,
               (i.close_price > i.ema_50) AS above_50ema,
               (i.close_price > i.ema_200) AS above_200ema,
               i.turnover_cr
        FROM indicators_daily i
        JOIN stocks_master m ON m.symbol = i.symbol
        WHERE i.trade_date = ?
          AND i.symbol IN ({placeholders})

        """
        try:
            df = db.execute(sql, [max_d]).fetchdf()
        except duckdb.Error:
            df = pd.DataFrame()

    if df.empty:
        return {"as_of": as_of_str, "pillars": [], "total_stocks": 0, "all_symbols": all_symbols}

    # Map each stock to its pillar
    df["pillar"] = df["symbol"].apply(lambda s: get_symbol_thematic_metadata(s)[0])
    df["role_desc"] = df["symbol"].apply(lambda s: get_symbol_thematic_metadata(s)[1])

    pillars_summary = []
    for pillar_name, mapping in NEXTGEN_TECH_UNIVERSE.items():
        sub_df = df[df["pillar"] == pillar_name]
        stock_count = len(sub_df)
        if stock_count == 0:
            continue

        avg_rs = float(sub_df["rs_percentile"].mean()) if pd.notna(sub_df["rs_percentile"].mean()) else 50.0
        avg_1m = float(sub_df["return_1m_pct"].mean()) if pd.notna(sub_df["return_1m_pct"].mean()) else 0.0
        avg_5d = float(sub_df["return_5d_pct"].mean()) if pd.notna(sub_df["return_5d_pct"].mean()) else 0.0
        breadth_50 = float((sub_df["above_50ema"].mean() * 100.0)) if pd.notna(sub_df["above_50ema"].mean()) else 0.0
        highs_count = int((sub_df["away_52w_high_pct"] <= 5.0).sum()) if "away_52w_high_pct" in sub_df else 0
        total_turnover = float(sub_df["turnover_cr"].sum()) if pd.notna(sub_df["turnover_cr"].sum()) else 0.0

        # Top 3 leaders in this pillar
        sorted_sub = sub_df.sort_values(by=["rs_percentile", "turnover_cr"], ascending=[False, False])
        top_syms = sorted_sub["symbol"].head(3).tolist()

        pillars_summary.append({
            "pillar_name": pillar_name,
            "stock_count": stock_count,
            "avg_rs": avg_rs,
            "avg_1m_pct": avg_1m,
            "avg_5d_pct": avg_5d,
            "breadth_50_pct": breadth_50,
            "highs_count": highs_count,
            "total_turnover_cr": total_turnover,
            "top_symbols": top_syms,
            "all_pillar_symbols": sorted_sub["symbol"].tolist(),
        })

    # Sort pillars by average RS
    pillars_summary.sort(key=lambda x: x["avg_rs"], reverse=True)

    return {
        "as_of": as_of_str,
        "pillars": pillars_summary,
        "total_stocks": len(df),
        "all_symbols": all_symbols,
        "raw_df": df,
    }


def query_thematic_constituents(
    db_path: Path,
    pillar_name: str | None = None,
    min_mcap: float = 0.0,
    limit: int = 60,
) -> pd.DataFrame:
    """Fetch complete list of thematic constituent stocks with candidate setups and exact role descriptions."""
    db_path = Path(db_path)
    if not db_path.exists():
        return pd.DataFrame()

    all_symbols = get_all_thematic_symbols()
    placeholders = ", ".join([repr(s) for s in all_symbols])

    with duckdb.connect(str(db_path), read_only=True) as db:
        max_d = db.execute("SELECT max(trade_date) FROM indicators_daily").fetchone()[0]
        if max_d is None:
            return pd.DataFrame()

        sql = f"""
        WITH latest AS (
            SELECT max(trade_date) AS d FROM indicators_daily
        ),
        cand AS (
            SELECT symbol, candidate_state, total_score, trigger_price, invalidation_price, first_resistance, reward_to_risk, why_now
            FROM candidate_daily
            WHERE trade_date = (SELECT max(trade_date) FROM candidate_daily)
        )
        SELECT i.symbol,
               coalesce(m.security_name, i.symbol) AS security_name,
               m.sector,
               m.industry,
               coalesce(m.market_cap_cr, 0) AS market_cap_cr,
               i.close_price,
               i.return_5d_pct,
               i.return_1m_pct,
               i.return_3m_pct,

               i.rs_percentile,
               coalesce(i.rvol, 1.0) AS rvol,
               i.delivery_pct,
               i.is_vcp,
               i.vcp_score,
               i.vcp_state,
               i.away_52w_high_pct,
               i.turnover_cr,
               c.candidate_state,
               c.total_score AS candidate_score,
               c.trigger_price,
               c.invalidation_price AS stop_loss,
               c.first_resistance AS target_price,
               c.reward_to_risk,
               c.why_now
        FROM indicators_daily i
        JOIN latest l ON i.trade_date = l.d
        JOIN stocks_master m ON m.symbol = i.symbol
        LEFT JOIN cand c ON c.symbol = i.symbol
        WHERE i.symbol IN ({placeholders})
          AND coalesce(m.market_cap_cr, 0) >= ?
        ORDER BY i.rs_percentile DESC NULLS LAST, i.turnover_cr DESC NULLS LAST
        LIMIT ?
        """

        try:
            df = db.execute(sql, [float(min_mcap), int(limit)]).fetchdf()
        except duckdb.Error:
            df = pd.DataFrame()

    if df.empty:
        return df

    df["pillar"] = df["symbol"].apply(lambda s: get_symbol_thematic_metadata(s)[0])
    df["role_desc"] = df["symbol"].apply(lambda s: get_symbol_thematic_metadata(s)[1])

    if pillar_name and pillar_name != "All Pillars":
        df = df[df["pillar"] == pillar_name]

    return df
