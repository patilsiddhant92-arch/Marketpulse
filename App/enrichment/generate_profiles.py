"""
Stock Enrichment Pipeline — Generate company profiles, thematic tags, and peer groups
for all NSE stocks using Gemini API with structured JSON output.

Usage:
    python -m App.enrichment.generate_profiles [--batch-size 50] [--resume]
    
Or standalone:
    python App/enrichment/generate_profiles.py [--batch-size 50] [--resume]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

import duckdb
from google import genai
from google.genai import types
from pydantic import BaseModel


# ── Pydantic Schemas ────────────────────────────────────────────────

class PeerEntry(BaseModel):
    peer_symbol: str
    similarity: str  # "direct_competitor", "supply_chain", "thematic"


class StockProfile(BaseModel):
    symbol: str
    company_name: str
    business_summary: str
    key_segments: list[str]
    core_products: list[str]
    thematic_tags: list[str]
    peers: list[PeerEntry]


class ProfileBatch(BaseModel):
    profiles: list[StockProfile]


# ── Constants ───────────────────────────────────────────────────────

MODEL = "gemini-3.5-flash-lite"
TEMPERATURE = 0.2
DEFAULT_BATCH_SIZE = 50

DB_MAIN = Path("Database/marketpulse.duckdb")
DB_USER = Path("Database/marketpulse_user.duckdb")

SYSTEM_PROMPT = """You are an expert Indian equity market analyst with deep knowledge of NSE-listed companies.

For each stock provided, generate:
1. company_name: Full registered name
2. business_summary: 2-3 concise sentences about what the company ACTUALLY does, its competitive position, and revenue drivers. Be specific.
3. key_segments: Main business divisions/segments (2-5 items)
4. core_products: Specific products or services (3-5 items)
5. thematic_tags: 3-5 macro investment themes (e.g. "China+1", "PLI Beneficiary", "EV Supply Chain", "Digital India", "Energy Transition", "Defence Indigenization", "Infra Capex", "Premiumization", "Rural Recovery", "Real Estate Upcycle", "Make in India", "Green Hydrogen", "Data Center Boom", "Hospitality Boom", "Banking Credit Growth", "Insurance Penetration", "Auto Upcycle", "Specialty Chemicals", "API/Pharma", "Agri Value Chain")
6. peers: 3-5 closest NSE-listed peers with similarity type. MUST be real NSE ticker symbols. Types: "direct_competitor", "supply_chain", "thematic"

IMPORTANT:
- All peer symbols MUST be real NSE ticker symbols
- Be specific in business_summary — avoid generic descriptions
- Use the exact symbol provided in input"""


# ── Schema Setup ────────────────────────────────────────────────────

def ensure_schema(user_db_path: Path) -> None:
    """Create enrichment tables if they don't exist."""
    with duckdb.connect(str(user_db_path)) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS company_profiles (
                symbol VARCHAR PRIMARY KEY,
                company_name VARCHAR,
                business_summary TEXT,
                key_segments TEXT,      -- JSON array stored as text
                core_products TEXT,     -- JSON array stored as text
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS thematic_tags (
                symbol VARCHAR,
                tag VARCHAR,
                PRIMARY KEY (symbol, tag)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS peer_groups (
                symbol VARCHAR,
                peer_symbol VARCHAR,
                similarity_type VARCHAR,
                PRIMARY KEY (symbol, peer_symbol)
            )
        """)
    print(f"[OK] Schema ensured in {db_path}")


# ── Data Loading ────────────────────────────────────────────────────

def load_all_symbols(db_path: Path) -> list[dict[str, Any]]:
    """Load all stocks from stocks_master."""
    with duckdb.connect(str(db_path), read_only=True) as db:
        df = db.execute("""
            SELECT symbol, security_name, broad_sector, sector,
                   broad_industry, industry, ROUND(market_cap_cr) as mcap_cr
            FROM stocks_master
            ORDER BY market_cap_cr DESC NULLS LAST
        """).fetchdf()
    return df.to_dict("records")


def load_completed_symbols(db_path: Path) -> set[str]:
    """Load symbols already enriched (for resume support)."""
    try:
        with duckdb.connect(str(db_path), read_only=True) as db:
            rows = db.execute("SELECT symbol FROM company_profiles").fetchall()
            return {r[0] for r in rows}
    except Exception:
        return set()


# ── Prompt Builder ──────────────────────────────────────────────────

def build_prompt(stocks: list[dict[str, Any]]) -> str:
    """Build the prompt for a batch of stocks."""
    lines = []
    for s in stocks:
        lines.append(
            f"- {s['symbol']} | {s['security_name']} | "
            f"Sector: {s['sector']} | Industry: {s['industry']} | "
            f"MCap: {s['mcap_cr']} Cr"
        )
    stock_list = "\n".join(lines)
    return f"""Generate structured company profiles for these NSE-listed stocks:

{stock_list}

Return one profile per stock. Use the exact symbol as provided."""


# ── Gemini API Call ─────────────────────────────────────────────────

def call_gemini(client: genai.Client, prompt: str, retries: int = 3) -> list[dict]:
    """Call Gemini API with structured output and retry logic."""
    for attempt in range(retries):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type='application/json',
                    response_json_schema=ProfileBatch.model_json_schema(),
                    temperature=TEMPERATURE,
                ),
            )
            result = json.loads(response.text)
            return result.get("profiles", [])
        except Exception as e:
            wait = 2 ** (attempt + 1)
            print(f"  [RETRY {attempt+1}/{retries}] {type(e).__name__}: {e}")
            if attempt < retries - 1:
                print(f"  Waiting {wait}s before retry...")
                time.sleep(wait)
            else:
                print(f"  [FAIL] Batch failed after {retries} attempts")
                raise
    return []


# ── Persist to DuckDB ───────────────────────────────────────────────

def persist_batch(user_db_path: Path, profiles: list[dict]) -> int:
    """Insert a batch of profiles into DuckDB tables. Returns count inserted."""
    inserted = 0
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with duckdb.connect(str(user_db_path)) as db:
        for p in profiles:
            sym = p.get("symbol", "").strip().upper()
            if not sym:
                continue

            # Upsert company_profiles
            db.execute("""
                INSERT INTO company_profiles (symbol, company_name, business_summary, key_segments, core_products, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (symbol) DO UPDATE SET
                    company_name = $2,
                    business_summary = $3,
                    key_segments = $4,
                    core_products = $5,
                    updated_at = $6
            """, [
                sym,
                p.get("company_name", ""),
                p.get("business_summary", ""),
                json.dumps(p.get("key_segments", [])),
                json.dumps(p.get("core_products", [])),
                now,
            ])

            # Upsert thematic_tags
            for tag in p.get("thematic_tags", []):
                tag = tag.strip()
                if tag:
                    db.execute("""
                        INSERT INTO thematic_tags (symbol, tag)
                        VALUES (?, ?)
                        ON CONFLICT DO NOTHING
                    """, [sym, tag])

            # Upsert peer_groups
            for peer in p.get("peers", []):
                peer_sym = peer.get("peer_symbol", "").strip().upper()
                sim_type = peer.get("similarity", "thematic")
                if peer_sym:
                    db.execute("""
                        INSERT INTO peer_groups (symbol, peer_symbol, similarity_type)
                        VALUES (?, ?, ?)
                        ON CONFLICT DO NOTHING
                    """, [sym, peer_sym, sim_type])

            inserted += 1
    return inserted


# ── Main Pipeline ───────────────────────────────────────────────────

def run_pipeline(batch_size: int = DEFAULT_BATCH_SIZE, resume: bool = True) -> None:
    """Run the full enrichment pipeline."""
    print("=" * 70)
    print("  STOCK ENRICHMENT PIPELINE")
    print("=" * 70)

    # Ensure schema
    ensure_schema(DB_USER)

    # Load stocks
    all_stocks = load_all_symbols(DB_MAIN)
    total = len(all_stocks)
    print(f"[OK] Loaded {total} stocks from stocks_master")

    # Resume support
    if resume:
        completed = load_completed_symbols(DB_USER)
        pending = [s for s in all_stocks if s["symbol"] not in completed]
        print(f"[OK] Already completed: {len(completed)} | Pending: {len(pending)}")
    else:
        pending = all_stocks
        print(f"[OK] Processing all {total} stocks (no resume)")

    if not pending:
        print("[DONE] All stocks already enriched!")
        return

    # Batch and process
    batches = [pending[i:i + batch_size] for i in range(0, len(pending), batch_size)]
    print(f"[OK] {len(batches)} batches of {batch_size}")
    print("-" * 70)

    client = genai.Client()
    total_done = len(all_stocks) - len(pending)
    total_errors = 0
    start_time = time.time()

    for batch_idx, batch in enumerate(batches):
        batch_num = batch_idx + 1
        symbols = [s["symbol"] for s in batch]
        print(f"\n[Batch {batch_num}/{len(batches)}] {len(batch)} stocks: {symbols[0]}...{symbols[-1]}")

        try:
            prompt = build_prompt(batch)
            profiles = call_gemini(client, prompt)
            count = persist_batch(DB_USER, profiles)
            total_done += count

            elapsed = time.time() - start_time
            rate = total_done / elapsed if elapsed > 0 else 0
            eta = (total - total_done) / rate if rate > 0 else 0

            print(f"  [OK] {count}/{len(batch)} saved | "
                  f"Progress: {total_done}/{total} ({100*total_done/total:.1f}%) | "
                  f"ETA: {eta/60:.1f} min")

            # Rate limiting — 1s pause between batches
            if batch_idx < len(batches) - 1:
                time.sleep(1.0)

        except Exception as e:
            total_errors += 1
            print(f"  [ERROR] Batch {batch_num} failed: {e}")
            # Continue to next batch
            if total_errors > 5:
                print(f"\n[ABORT] Too many errors ({total_errors}). Stopping pipeline.")
                print(f"  Re-run with --resume to continue from where we left off.")
                break

    elapsed = time.time() - start_time
    print("\n" + "=" * 70)
    print(f"  PIPELINE COMPLETE")
    print(f"  Total: {total_done}/{total} | Errors: {total_errors} | Time: {elapsed/60:.1f} min")
    print("=" * 70)

    # Final stats
    with duckdb.connect(str(DB_USER), read_only=True) as db:
        cp = db.execute("SELECT COUNT(*) FROM company_profiles").fetchone()[0]
        tt = db.execute("SELECT COUNT(DISTINCT symbol) FROM thematic_tags").fetchone()[0]
        pg = db.execute("SELECT COUNT(DISTINCT symbol) FROM peer_groups").fetchone()[0]
        unique_tags = db.execute("SELECT COUNT(DISTINCT tag) FROM thematic_tags").fetchone()[0]
        print(f"  Profiles: {cp} | Tagged: {tt} | Peers: {pg} | Unique themes: {unique_tags}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate stock enrichment profiles via Gemini API")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Stocks per API call")
    parser.add_argument("--resume", action="store_true", default=True, help="Resume from last checkpoint")
    parser.add_argument("--no-resume", action="store_true", help="Start fresh (re-process all)")
    args = parser.parse_args()

    if args.no_resume:
        args.resume = False

    run_pipeline(batch_size=args.batch_size, resume=args.resume)
