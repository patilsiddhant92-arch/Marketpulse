import argparse
import csv
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from config import ARCHIVE_DIR, DAILY_DIR, INPUT_DIR

try:
    from curl_cffi import requests
except ImportError as exc:  # pragma: no cover - exercised by batch setup instead
    raise SystemExit("Missing dependency: curl_cffi. Run Scripts\\_ensure_venv.bat first.") from exc


NSE_HOME = "https://www.nseindia.com"
NSE_ARCHIVES = "https://nsearchives.nseindia.com"
DOWNLOAD_ROOT = INPUT_DIR / "downloads"
REPORT_KEYS = {
    "bhavcopy": "CM-BHAVDATA-FULL",
    "52-week high-low": "CM-52 WEEK-HIGH_LOW",
    "price band": "CM-PRICEBAND-COMPLETE-LIST",
    "PE": "CM-PE-RATIO-CSV",
    "market activity": "CM-MARKET-ACTIVITY-REPORT",
    "market cap zip": "CM-BHAVCOPY-PR-ZIP",
    "bulk": "CM-BULK-DEAL",
    "block": "CM-BLOCK-DEAL",
}


@dataclass(frozen=True)
class ReportSpec:
    label: str
    output_name: str
    candidates: tuple[str, ...]
    required_columns: tuple[str, ...]


class DownloadError(RuntimeError):
    pass


def parse_date(value: str | None) -> datetime:
    if not value:
        return datetime.now()
    for fmt in ("%d%m%Y", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise argparse.ArgumentTypeError("Date must be DDMMYYYY.")


def choose_report_date() -> datetime:
    today = datetime.now()
    today_text = ddmmyyyy(today)
    while True:
        print()
        print("Select NSE report date before download:")
        print(f"  1. Today's date ({today_text})")
        print("  2. Other date")
        choice = input("Enter 1 or 2: ").strip()
        if choice == "1":
            print(f"Using report date: {today_text}")
            return today
        if choice == "2":
            value = input("Enter date as DDMMYYYY: ").strip()
            try:
                day = parse_date(value)
            except argparse.ArgumentTypeError as exc:
                print(exc)
                continue
            print(f"Using report date: {ddmmyyyy(day)}")
            return day
        print("Please enter 1 for today's date or 2 to type another date.")


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    counter = 2
    while True:
        candidate = path.with_name(f"{stem} ({counter}){suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def make_session() -> requests.Session:
    session = requests.Session(impersonate="chrome124")
    session.headers.update(
        {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "accept-language": "en-US,en;q=0.9",
            "cache-control": "no-cache",
            "referer": f"{NSE_HOME}/all-reports",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
        }
    )
    for url in (NSE_HOME, f"{NSE_HOME}/all-reports"):
        try:
            session.get(url, timeout=20)
        except Exception:
            pass
    return session


def trading_date_matches(value: str, day: datetime) -> bool:
    for fmt in ("%d-%b-%Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(value, fmt).date() == day.date()
        except ValueError:
            continue
    return False


def discover_daily_report_urls(session: requests.Session, day: datetime) -> dict[str, str]:
    try:
        response = session.get(
            f"{NSE_HOME}/api/daily-reports?key=CM",
            timeout=30,
            headers={"accept": "application/json,*/*", "referer": f"{NSE_HOME}/all-reports"},
        )
        if response.status_code != 200:
            return {}
        payload = response.json()
    except Exception:
        return {}

    urls: dict[str, str] = {}
    key_to_label = {value: key for key, value in REPORT_KEYS.items()}
    for rows in payload.values():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            if not trading_date_matches(str(row.get("tradingDate", "")), day):
                continue
            label = key_to_label.get(str(row.get("fileKey", "")))
            path = str(row.get("filePath", ""))
            name = str(row.get("fileActlName", ""))
            if label and path and name:
                urls[label] = f"{path}{name}"
    return urls


def ddmmyyyy(day: datetime) -> str:
    return day.strftime("%d%m%Y")


def ddmmyy(day: datetime) -> str:
    return day.strftime("%d%m%y")


def nse_query_date(day: datetime) -> str:
    return day.strftime("%d-%m-%Y")


def with_discovered(discovered: dict[str, str], label: str, candidates: tuple[str, ...]) -> tuple[str, ...]:
    url = discovered.get(label)
    return (url, *candidates) if url else candidates


def report_specs(day: datetime, discovered: dict[str, str]) -> list[ReportSpec]:
    long_date = ddmmyyyy(day)
    short_date = ddmmyy(day)
    return [
        ReportSpec(
            "bhavcopy",
            f"sec_bhavdata_full_{long_date}.csv",
            with_discovered(discovered, "bhavcopy", (
                f"{NSE_ARCHIVES}/products/content/sec_bhavdata_full_{long_date}.csv",
                f"{NSE_ARCHIVES}/archives/equities/bhavcopy/sec_bhavdata_full_{long_date}.csv",
                f"{NSE_ARCHIVES}/content/sec_bhavdata_full_{long_date}.csv",
            )),
            ("SYMBOL", "DATE1", "CLOSE_PRICE"),
        ),
        ReportSpec(
            "52-week high-low",
            f"CM_52_wk_High_low_{long_date}.csv",
            with_discovered(discovered, "52-week high-low", (
                f"{NSE_ARCHIVES}/content/CM_52_wk_High_low_{long_date}.csv",
                f"{NSE_ARCHIVES}/archives/equities/mkt/CM_52_wk_High_low_{long_date}.csv",
                f"{NSE_ARCHIVES}/products/content/CM_52_wk_High_low_{long_date}.csv",
            )),
            ("Symbol", "Series"),
        ),
        ReportSpec(
            "price band",
            f"sec_list_{long_date}.csv",
            with_discovered(discovered, "price band", (
                f"{NSE_ARCHIVES}/content/equities/sec_list_{long_date}.csv",
                f"{NSE_ARCHIVES}/archives/equities/securitylist/sec_list_{long_date}.csv",
                f"{NSE_ARCHIVES}/products/content/sec_list_{long_date}.csv",
            )),
            ("Symbol", "Series", "Band"),
        ),
        ReportSpec(
            "PE",
            f"PE_{short_date}.csv",
            with_discovered(discovered, "PE", (
                f"{NSE_ARCHIVES}/content/equities/peDetail/PE_{short_date}.csv",
                f"{NSE_ARCHIVES}/archives/equities/bhavcopy/pr/PE_{short_date}.csv",
                f"{NSE_ARCHIVES}/archives/equities/bhavcopy/pr/PE{short_date}.csv",
                f"{NSE_ARCHIVES}/products/content/PE_{short_date}.csv",
            )),
            ("SYMBOL",),
        ),
        ReportSpec(
            "market activity",
            f"MA{short_date}.csv",
            with_discovered(discovered, "market activity", (
                f"{NSE_ARCHIVES}/archives/equities/mkt/MA{short_date}.csv",
                f"{NSE_ARCHIVES}/archives/equities/bhavcopy/pr/MA{short_date}.csv",
                f"{NSE_ARCHIVES}/products/content/MA{short_date}.csv",
            )),
            (),
        ),
    ]


def fetch_bytes(session: requests.Session, url: str) -> bytes:
    response = session.get(url, timeout=45)
    if response.status_code != 200:
        raise DownloadError(f"HTTP {response.status_code}")
    data = response.content
    if not data:
        raise DownloadError("empty response")
    lower = data[:500].lower()
    if b"<html" in lower or b"<!doctype html" in lower:
        raise DownloadError("HTML response instead of report")
    return data


def download_first(session: requests.Session, candidates: tuple[str, ...], dest: Path) -> str:
    failures: list[str] = []
    for url in candidates:
        try:
            data = fetch_bytes(session, url)
            dest.write_bytes(data)
            return url
        except Exception as exc:
            failures.append(f"{url} ({exc})")
    joined = "\n  - ".join(failures)
    raise DownloadError(f"Could not download {dest.name}. Tried:\n  - {joined}")


def read_csv_headers(path: Path) -> list[list[str]]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    headers: list[list[str]] = []
    for line in text.splitlines():
        if line.strip():
            headers.append(next(csv.reader([line])))
        if len(headers) >= 10:
            break
    return headers


def validate_csv(path: Path, required_columns: tuple[str, ...], allow_no_records: bool = False) -> None:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if not text.strip():
        raise DownloadError(f"{path.name} is empty.")
    if allow_no_records and "NO RECORDS" in text.upper():
        return
    if required_columns:
        required = {col.upper() for col in required_columns}
        for header_row in read_csv_headers(path):
            header = {col.strip().upper() for col in header_row}
            if required.issubset(header):
                return
        missing = list(required)
        if missing:
            raise DownloadError(f"{path.name} is missing columns: {', '.join(missing)}")


def download_market_cap(session: requests.Session, day: datetime, stage_dir: Path, discovered: dict[str, str]) -> str:
    short_date = ddmmyy(day)
    long_date = ddmmyyyy(day)
    zip_path = stage_dir / f"PR{short_date}.zip"
    output_path = stage_dir / f"mcap{long_date}.csv"
    pr_candidates = (
        f"{NSE_ARCHIVES}/archives/equities/bhavcopy/pr/PR{short_date}.zip",
        f"{NSE_ARCHIVES}/products/content/PR{short_date}.zip",
    )
    if discovered.get("market cap zip"):
        pr_candidates = (discovered["market cap zip"], *pr_candidates)
    url = download_first(
        session,
        pr_candidates,
        zip_path,
    )
    with zipfile.ZipFile(zip_path) as archive:
        names = [name for name in archive.namelist() if re.search(r"mcap.*\.csv$", name, re.I)]
        if not names:
            raise DownloadError(f"PR{short_date}.zip did not contain an mcap CSV.")
        with archive.open(names[0]) as source:
            output_path.write_bytes(source.read())
    validate_csv(output_path, ("Trade Date", "Symbol", "Market Cap(Rs.)"))
    return url


def deals_from_api(session: requests.Session, day: datetime, deal_type: str, dest: Path) -> str:
    date_arg = nse_query_date(day)
    api_names = {
        "bulk": ("bulk-deals", "bulk_deals"),
        "block": ("block-deals", "block_deals"),
    }
    endpoint, option_type = api_names[deal_type]
    candidates = (
        f"{NSE_HOME}/api/historical/{endpoint}?from={date_arg}&to={date_arg}",
        f"{NSE_HOME}/api/historicalOR/bulk-block-short-deals?optionType={option_type}&from={date_arg}&to={date_arg}",
    )
    failures: list[str] = []
    for url in candidates:
        try:
            response = session.get(url, timeout=45, headers={"accept": "application/json,*/*"})
            if response.status_code != 200:
                raise DownloadError(f"HTTP {response.status_code}")
            payload = response.json()
            rows = payload.get("data") if isinstance(payload, dict) else None
            if rows is None:
                rows = payload if isinstance(payload, list) else []
            write_deals_csv(dest, rows)
            validate_csv(dest, ("Date", "Symbol", "Buy/Sell"), allow_no_records=True)
            return url
        except Exception as exc:
            failures.append(f"{url} ({exc})")
    joined = "\n  - ".join(failures)
    raise DownloadError(f"Could not download {deal_type}. Tried:\n  - {joined}")


def normalize_key(row: dict, *names: str) -> str:
    lowered = {str(k).strip().lower().replace("_", " "): v for k, v in row.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value is not None:
            return str(value).strip()
    return ""


def write_deals_csv(path: Path, rows: list[dict]) -> None:
    columns = [
        "Date",
        "Symbol",
        "Security Name",
        "Client Name",
        "Buy/Sell",
        "Quantity Traded",
        "Trade Price / Wght. Avg. Price",
        "Remarks",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        if not rows:
            writer.writerow(["NO RECORDS", "", "", "", "", "", "", ""])
            return
        for row in rows:
            writer.writerow(
                [
                    normalize_key(row, "date", "BD_DT_DATE", "TIMESTAMP"),
                    normalize_key(row, "symbol", "BD_SYMBOL", "SYMBOL"),
                    normalize_key(row, "security name", "BD_SCRIP_NAME", "SECURITY_NAME"),
                    normalize_key(row, "client name", "BD_CLIENT_NAME", "CLIENT_NAME"),
                    normalize_key(row, "buy/sell", "BD_BUY_SELL", "BUY_SELL"),
                    normalize_key(row, "quantity traded", "BD_QTY_TRD", "QUANTITY_TRADED"),
                    normalize_key(row, "trade price / wght. avg. price", "BD_TP_WATP", "TRADE_PRICE"),
                    normalize_key(row, "remarks", "REMARKS"),
                ]
            )


def download_latest_deal_csv(session: requests.Session, deal_type: str, dest: Path) -> str:
    return download_first(
        session,
        (
            f"{NSE_ARCHIVES}/content/equities/{deal_type}.csv",
            f"{NSE_ARCHIVES}/products/content/{deal_type}.csv",
        ),
        dest,
    )


def download_deals(session: requests.Session, day: datetime, stage_dir: Path, discovered: dict[str, str]) -> dict[str, str]:
    sources: dict[str, str] = {}
    for deal_type in ("bulk", "block"):
        dest = stage_dir / f"{deal_type}.csv"
        if discovered.get(deal_type):
            try:
                sources[deal_type] = download_first(session, (discovered[deal_type],), dest)
                validate_csv(dest, ("Date", "Symbol", "Buy/Sell"), allow_no_records=True)
                continue
            except DownloadError:
                pass
        try:
            sources[deal_type] = deals_from_api(session, day, deal_type, dest)
        except DownloadError:
            sources[deal_type] = download_latest_deal_csv(session, deal_type, dest)
            validate_csv(dest, ("Date", "Symbol", "Buy/Sell"), allow_no_records=True)
    return sources


def clean_stage(stage_dir: Path) -> None:
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)


def validate_stage(stage_dir: Path, expected_names: list[str]) -> None:
    missing = [name for name in expected_names if not (stage_dir / name).exists()]
    if missing:
        raise DownloadError(f"Stage is missing: {', '.join(missing)}")


def archive_daily_inputs(report_day: datetime | None = None) -> list[tuple[Path, Path]]:
    """Move current Input/daily files into archive. bulk/block get dated names when possible."""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    moved: list[tuple[Path, Path]] = []
    if not DAILY_DIR.exists():
        return moved
    # Infer date from bhavcopy name if not provided
    day = report_day
    if day is None:
        for path in DAILY_DIR.glob("sec_bhavdata_full_*.csv"):
            try:
                day = parse_date(path.name[len("sec_bhavdata_full_") : path.name.rfind(".")])
                break
            except Exception:
                continue
    for source in sorted(DAILY_DIR.iterdir()):
        if not source.is_file():
            continue
        out_name = source.name
        lower = source.name.lower()
        if day is not None and lower in {"bulk.csv", "block.csv"}:
            out_name = f"{source.stem}_{ddmmyyyy(day)}{source.suffix}"
        target = unique_path(ARCHIVE_DIR / out_name)
        shutil.move(str(source), str(target))
        moved.append((source, target))
    return moved


def clear_daily_dir() -> None:
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    for item in DAILY_DIR.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


def install_stage(stage_dir: Path, expected_names: list[str], dry_run: bool) -> list[Path]:
    if dry_run:
        return [stage_dir / name for name in expected_names]

    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    installed: list[Path] = []
    for name in expected_names:
        target = DAILY_DIR / name
        if target.exists():
            target.unlink()
        shutil.copy2(stage_dir / name, target)
        installed.append(target)
    return installed


def bhavcopy_embedded_date(path: Path) -> datetime | None:
    """Parse DATE1 from a bhavcopy CSV (first data row)."""
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except Exception:
        return None
    reader = csv.reader(text.splitlines())
    header = None
    for row in reader:
        if not row or not any(cell.strip() for cell in row):
            continue
        if header is None:
            header = [c.strip().upper() for c in row]
            continue
        try:
            idx = header.index("DATE1")
        except ValueError:
            return None
        if idx >= len(row):
            return None
        raw = row[idx].strip()
        for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
        return None
    return None


def session_available(session: requests.Session, day: datetime) -> bool:
    """True when NSE has a bhavcopy for this calendar date with matching DATE1."""
    discovered = discover_daily_report_urls(session, day)
    if discovered.get("bhavcopy"):
        return True
    long_date = ddmmyyyy(day)
    candidates = (
        f"{NSE_ARCHIVES}/products/content/sec_bhavdata_full_{long_date}.csv",
        f"{NSE_ARCHIVES}/archives/equities/bhavcopy/sec_bhavdata_full_{long_date}.csv",
        f"{NSE_ARCHIVES}/content/sec_bhavdata_full_{long_date}.csv",
    )
    stage = DOWNLOAD_ROOT / "_probe"
    stage.mkdir(parents=True, exist_ok=True)
    probe = stage / f"probe_{long_date}.csv"
    try:
        download_first(session, candidates, probe)
        embedded = bhavcopy_embedded_date(probe)
        if embedded is None:
            return False
        return embedded.date() == day.date()
    except Exception:
        return False
    finally:
        if probe.exists():
            try:
                probe.unlink()
            except OSError:
                pass


def resolve_auto_date(lookback_days: int = 7) -> datetime:
    """
    Pick the latest NSE session with published reports.
    Walks back from local today (not only weekdays — holidays still 404).
    """
    session = make_session()
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    tried: list[str] = []
    for offset in range(0, lookback_days + 1):
        day = today - timedelta(days=offset)
        label = day.strftime("%d-%m-%Y")
        tried.append(label)
        print(f"Checking NSE session availability: {label}...")
        if session_available(session, day):
            print(f"Using report date: {ddmmyyyy(day)}")
            return day
    raise DownloadError(
        "No published NSE equity session found in lookback. Tried: " + ", ".join(tried)
    )


def download_session_to_stage(day: datetime, stage_dir: Path) -> list[str]:
    """Download and validate a full report set into stage_dir. Returns expected file names."""
    clean_stage(stage_dir)
    session = make_session()
    discovered = discover_daily_report_urls(session, day)
    specs = report_specs(day, discovered)
    expected_names = [spec.output_name for spec in specs]
    expected_names.insert(1, f"mcap{ddmmyyyy(day)}.csv")
    expected_names.extend(["bulk.csv", "block.csv"])

    print(f"Downloading NSE reports for {day.strftime('%d-%m-%Y')}...")
    for spec in specs:
        path = stage_dir / spec.output_name
        download_first(session, spec.candidates, path)
        validate_csv(path, spec.required_columns)
        if spec.label == "bhavcopy":
            embedded = bhavcopy_embedded_date(path)
            if embedded is None or embedded.date() != day.date():
                raise DownloadError(
                    f"Bhavcopy DATE1 mismatch for {ddmmyyyy(day)} "
                    f"(got {embedded.date() if embedded else 'none'})."
                )
        print(f"  OK {spec.output_name}")

    download_market_cap(session, day, stage_dir, discovered)
    print(f"  OK mcap{ddmmyyyy(day)}.csv")

    download_deals(session, day, stage_dir, discovered)
    print("  OK bulk.csv")
    print("  OK block.csv")

    validate_stage(stage_dir, expected_names)
    return expected_names


def run(day: datetime, dry_run: bool) -> int:
    """
    Download full report set for `day`.
    Stage-first: Input/daily is only replaced after the full set validates.
    """
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    stage_dir = DOWNLOAD_ROOT / ddmmyyyy(day)

    expected_names = download_session_to_stage(day, stage_dir)

    if dry_run:
        print()
        print(f"Dry run complete. Files are staged in: {stage_dir}")
        for name in expected_names:
            print(f"  {name}")
        return 0

    # Mutate daily only after success
    previous_day = None
    if DAILY_DIR.exists():
        for path in DAILY_DIR.glob("sec_bhavdata_full_*.csv"):
            try:
                previous_day = parse_date(path.name[len("sec_bhavdata_full_") : path.name.rfind(".")])
                break
            except Exception:
                continue
    archived = archive_daily_inputs(previous_day)
    clear_daily_dir()
    if archived:
        print(f"Archived {len(archived)} existing daily files to {ARCHIVE_DIR}.")
    else:
        print("No existing daily files to archive.")

    installed = install_stage(stage_dir, expected_names, dry_run=False)
    print()
    print(f"Download complete. Files installed in: {DAILY_DIR}")
    for path in installed:
        print(f"  {path.name}")
    print()
    print("Next: Append_MarketPulse.bat  OR  Run_MarketPulse_Auto.bat / daily_pipeline.py")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Download and stage NSE daily MarketPulse files.")
    parser.add_argument("--date", type=parse_date, default=None, help="Report date as DDMMYYYY.")
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Non-interactive: pick latest published NSE session (for Task Scheduler).",
    )
    parser.add_argument("--lookback", type=int, default=7, help="Days to look back with --auto (default 7).")
    parser.add_argument("--dry-run", action="store_true", help="Download and validate without replacing Input\\daily.")
    args = parser.parse_args()
    try:
        if args.date is not None:
            day = args.date
        elif args.auto:
            day = resolve_auto_date(lookback_days=max(1, args.lookback))
        else:
            day = choose_report_date()
        return run(day, args.dry_run)
    except Exception as exc:
        print()
        print(f"Download failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
