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

DEFENCE_UNIVERSE: dict[str, dict[str, str]] = {
    "Aerospace & Avionics": {
        "HAL": "Hindustan Aeronautics - Tejas LCA Fighter Jets, Helicopters & Sukhoi Upgrade",
        "BEL": "Bharat Electronics - Radars, Electronic Warfare (EW), Missile Guidance Systems",
        "DATAPATTNS": "Data Patterns - Airborne Radars, Electronic Warfare & Satellite Payloads",
        "ASTRAMICRO": "Astra Microwave - Radar Electronics, EW Subsystems & Space Modules",
        "PARAS": "Paras Defence - Submarine Periscopes, Space Optics & Anti-Drone Systems",
        "DCXINDIA": "DCX Systems - System Integration & Cable Harnessing for Defense OEMs",
    },
    "Shipbuilding & Marine Warfare": {
        "MAZDOCK": "Mazagon Dock Shipbuilders - Scorpene Submarines & Guided Missile Destroyers",
        "COCHINSHIP": "Cochin Shipyard - Indigenous Aircraft Carrier & Next-Gen Corvettes",
        "GRSE": "Garden Reach Shipbuilders - Anti-Submarine Warfare Corvettes & Frigates",
    },
    "Missiles, Artillery & Armor": {
        "BDL": "Bharat Dynamics - Akash, BrahMos, Astra Missiles & Torpedoes",
        "SOLARINDS": "Solar Industries - Pinaka Rocket Propellants, High-Energy Warheads & Loitering Munitions",
        "ZENITH": "Zen Technologies - Anti-Drone Combat Systems & Military Simulators",
        "MIDHANI": "Mishra Dhatu Nigam - Superalloys & Titanium Armor for Missiles and Space",
        "BEML": "BEML - Heavy Mobility Vehicles for Pinaka/Missile Launchers & Combat Armor",
        "MTARTECH": "MTAR Technologies - Precision Machined Assemblies for Missiles & Chandrayaan",
    },
}

POWER_GRID_UNIVERSE: dict[str, dict[str, str]] = {
    "Heavy Grid Equipment & Transformers": {
        "ABB": "Heavy Electrification, Substation Switchgears & Grid Automation",
        "SIEMENS": "HVDC Grid Interconnections, Gas-Insulated Switchgears (GIS)",
        "POWERINDIA": "Hitachi Energy - HVDC Mega Transmission Links & Substation Automation",
        "GVT&D": "GE Vernova T&D - Ultra-High Voltage Grid Substations & Switchgears",
        "TARIL": "Transformers & Rectifiers - 765kV Power Utility Transformers",
        "VOLTAMP": "Dry-Type & Industrial Distribution Transformers",
        "SCHNEIDER": "Medium-Voltage Switchgear & Smart Grid Distribution",
    },
    "Transmission EPC & Towers": {
        "POWERGRID": "Power Grid Corp of India - Central Transmission Utility (CTU) Monopoly",
        "KPIL": "Kalpataru Projects - Turnkey Power Transmission Lines & Substations EPC",
        "KEC": "KEC International - EHV Transmission Line EPC & Railway Electrification",
        "SKIPPER": "Skipper - High-Tonnage Power Transmission Towers & Monopoles",
    },
    "Power Generation & Wind/Solar": {
        "NTPC": "NTPC - Mega Power Utility & Green Hydrogen / Renewable Expansion",
        "TATAPOWER": "Tata Power - Integrated Generation, Transmission, Solar EPC & EV Charging",
        "BHEL": "Bharat Heavy Electricals - Supercritical Thermal & Nuclear Turbines EPC",
        "SUZLON": "Suzlon Energy - Wind Turbine OEM & Turnkey Wind Energy EPC",
        "INOXWIND": "Inox Wind - 3MW+ Mega Wind Turbine Generators OEM",
    },
    "Power Financing & Exchanges": {
        "PFC": "Power Finance Corp - Sovereign Power & Green Capex Lender",
        "REC": "REC Limited - Power Generation, Transmission & Distribution NBFC",
        "IEX": "Indian Energy Exchange - Spot Electricity & Green Trading Market",
    },
}

RAILWAYS_UNIVERSE: dict[str, dict[str, str]] = {
    "Rolling Stock & Wagons": {
        "TITAGARH": "Titagarh Rail Systems - Vande Bharat Trainsets & Metro Coaches OEM",
        "JUPITERWAG": "Jupiter Wagons - Freight Wagons, Braking Systems & Disc Brakes",
        "TEXRAIL": "Texmaco Rail & Engineering - Heavy Freight Wagons, Steel Bridges & Bogies",
        "BEML": "BEML - Vande Bharat Sleeper Trains & Metro Coach Manufacturing",
    },
    "Railway Infrastructure & Track EPC": {
        "RVNL": "Rail Vikas Nigam - Turnkey Railway Track Doubling, High-Speed Lines & Bridges",
        "IRCON": "Ircon International - Specialized Rail, Tunnels, Bridges & Turnkey EPC",
        "RAILTEL": "RailTel Corp - Modern Railway Signaling (KAVACH), Telecom & Edge Data",
        "RITES": "RITES - Railway Design Consultancy, Rolling Stock Leasing & Export EPC",
    },
    "Financing, Catering & Freight": {
        "IRCTC": "IRCTC - Monopolistic Online Rail Ticketing, Catering & Rail Tourism",
        "IRFC": "Indian Railway Finance Corp - Sovereign Non-Banking Financier for Rail Assets",
        "CONCOR": "Container Corp of India - Multi-Modal Rail Freight & Inland Container Depots",
    },
}

EMS_UNIVERSE: dict[str, dict[str, str]] = {
    "Precision EMS & Box Build": {
        "DIXON": "Dixon Technologies - Consumer Electronics, Mobile PLI, Laptops & IT Hardware",
        "KAYNES": "Kaynes Technology - Industrial, Automotive & Aerospace Precision EMS",
        "SYRMA": "Syrma SGS - Precision Box-Build, RFID & Power Electronics Manufacturing",
        "AVALON": "Avalon Technologies - High-Complexity Cable Assemblies, Box-Build & Aerospace",
        "CYIENTDLM": "Cyient DLM - Defense & Aerospace Electronic Manufacturing Services",
        "PGEL": "PG Electroplast - Consumer Appliances, Air Conditioners & Plastic Molding EMS",
        "AMBER": "Amber Enterprises - Turnkey HVAC & Room AC Electronics Assembly",
        "CENTUM": "Centum Electronics - Strategic Defense, Space & Telecom Electronics",
        "IKIO": "IKIO Lighting - Precision LED & Architectural Electronics Manufacturing",
        "TEJASNET": "Tejas Networks - Optical, Broadband & Wireless Networking Equipment EMS",
        "DCXINDIA": "DCX Systems - Electronic Subsystems, Cable Harnessing & Defense Box-Build",
    },
}

REALTY_UNIVERSE: dict[str, dict[str, str]] = {
    "Real Estate Developers": {
        "DLF": "DLF - Super-Luxury Residential & Commercial CyberCity Portfolio",
        "GODREJPROP": "Godrej Properties - Pan-India Premium Residential Development",
        "PRESTIGE": "Prestige Estates - Mega Residential & Commercial Campuses",
        "OBEROIRLTY": "Oberoi Realty - High-End Luxury Residential & Mixed-Use Projects",
        "BRIGADE": "Brigade Enterprises - Integrated Townships & Commercial Tech Parks",
        "SOBHA": "Sobha - Backward-Integrated Luxury Residential & Contractual Construction",
        "PHOENIXLTD": "Phoenix Mills - Flagship Destination Malls & Retail Entertainment",
    },
    "Building Materials & Cabling": {
        "ASTRAL": "Astral - CPVC Plumbing Pipes, Water Tanks & Adhesives",
        "SUPREMEIND": "Supreme Industries - PVC/CPVC Piping, Industrial Plastics & Packaging",
        "POLYCAB": "Polycab India - Extra High Voltage Cabling & Residential Wires",
        "KEI": "KEI Industries - EHV Power Transmission Cables & Wires",
        "HAVELLS": "Havells India - Industrial Switchgear, Cables, Lighting & FMEG",
        "KAJARIACER": "Kajaria Ceramics - Vitrified & Ceramic Wall/Floor Tiles",
        "CERA": "Cera Sanitaryware - Sanitaryware, Faucets & Bath Fixtures",
    },
}

THEMATIC_UNIVERSES: dict[str, dict[str, dict[str, str]]] = {
    "Next-Gen Tech": NEXTGEN_TECH_UNIVERSE,
    "Defence & Aerospace": DEFENCE_UNIVERSE,
    "Power & Grid Capex": POWER_GRID_UNIVERSE,
    "Railways Infrastructure": RAILWAYS_UNIVERSE,
    "EMS & Precision": EMS_UNIVERSE,
    "Real Estate & Building": REALTY_UNIVERSE,
}


def get_all_thematic_symbols(theme_name: str = "Next-Gen Tech") -> list[str]:
    """Get flat unique list of symbols for the given theme or all themes."""
    if theme_name == "All":
        syms: list[str] = []
        for universe in THEMATIC_UNIVERSES.values():
            for pillar in universe.values():
                syms.extend(pillar.keys())
        return sorted(set(syms))

    target_universe = THEMATIC_UNIVERSES.get(theme_name, NEXTGEN_TECH_UNIVERSE)
    syms = []
    for pillar in target_universe.values():
        syms.extend(pillar.keys())
    return sorted(set(syms))


def get_symbol_thematic_metadata(symbol: str, theme_name: str | None = None) -> tuple[str, str]:
    """Return (pillar_name, role_description) for a symbol."""
    if theme_name and theme_name in THEMATIC_UNIVERSES:
        for pillar_name, mapping in THEMATIC_UNIVERSES[theme_name].items():
            if symbol in mapping:
                return pillar_name, mapping[symbol]

    # Search in default Next-Gen Tech first, then fallback across all universes
    for pillar_name, mapping in NEXTGEN_TECH_UNIVERSE.items():
        if symbol in mapping:
            return pillar_name, mapping[symbol]

    for uni_name, uni in THEMATIC_UNIVERSES.items():
        for pillar_name, mapping in uni.items():
            if symbol in mapping:
                return pillar_name, mapping[symbol]

    return "Thematic Constituent", "Ecosystem Constituent"


def query_thematic_overview(db_path: Path, theme_name: str = "Next-Gen Tech") -> dict[str, Any]:
    """Aggregate momentum, breadth, and leadership metrics across thematic pillars."""
    db_path = Path(db_path)
    if not db_path.exists():
        return {"as_of": None, "theme_name": theme_name, "pillars": [], "total_stocks": 0, "all_symbols": []}

    target_universe = THEMATIC_UNIVERSES.get(theme_name, NEXTGEN_TECH_UNIVERSE)
    all_symbols = get_all_thematic_symbols(theme_name)
    if not all_symbols:
        return {"as_of": None, "theme_name": theme_name, "pillars": [], "total_stocks": 0, "all_symbols": []}

    placeholders = ", ".join([repr(s) for s in all_symbols])

    with duckdb.connect(str(db_path), read_only=True) as db:
        # 1. Latest trade date
        max_d = db.execute("SELECT max(trade_date) FROM indicators_daily").fetchone()[0]
        if max_d is None:
            return {"as_of": None, "theme_name": theme_name, "pillars": [], "total_stocks": 0, "all_symbols": all_symbols}

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
        return {"as_of": as_of_str, "theme_name": theme_name, "pillars": [], "total_stocks": 0, "all_symbols": all_symbols}

    # Map each stock to its pillar
    df["pillar"] = df["symbol"].apply(lambda s: get_symbol_thematic_metadata(s, theme_name)[0])
    df["role_desc"] = df["symbol"].apply(lambda s: get_symbol_thematic_metadata(s, theme_name)[1])

    pillars_summary = []
    for pillar_name, mapping in target_universe.items():
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
        "theme_name": theme_name,
        "pillars": pillars_summary,
        "total_stocks": len(df),
        "all_symbols": all_symbols,
        "raw_df": df,
    }


def query_thematic_constituents(
    db_path: Path,
    pillar_name: str | None = None,
    theme_name: str = "Next-Gen Tech",
    min_mcap: float = 0.0,
    limit: int = 60,
) -> pd.DataFrame:
    """Fetch complete list of thematic constituent stocks with candidate setups and exact role descriptions."""
    db_path = Path(db_path)
    if not db_path.exists():
        return pd.DataFrame()

    all_symbols = get_all_thematic_symbols(theme_name)
    if not all_symbols:
        return pd.DataFrame()

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

    df["pillar"] = df["symbol"].apply(lambda s: get_symbol_thematic_metadata(s, theme_name)[0])
    df["role_desc"] = df["symbol"].apply(lambda s: get_symbol_thematic_metadata(s, theme_name)[1])

    if pillar_name and pillar_name != "All Pillars":
        df = df[df["pillar"] == pillar_name]

    return df
