from pathlib import Path
import argparse
import sys

from config import DAILY_DIR, REQUIRED_DAILY_PATTERNS
from build_database import main as build_database


def validate_daily_folder() -> None:
    missing = []
    for label, pattern in REQUIRED_DAILY_PATTERNS.items():
        if label in {"bulk", "block"}:
            continue
        if not list(Path(DAILY_DIR).glob(pattern)):
            missing.append(f"{label}: {pattern}")
    if missing:
        joined = "\n  - ".join(missing)
        raise FileNotFoundError(f"Missing required daily files:\n  - {joined}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Daily update wrapper. Runs strict validation then full build. For catch-up after missed uploads: place missed bhav/deal/reference files (any dates) into Input/daily/ and run python Scripts/build_database.py directly (it performs a complete history rebuild from archive + everything in daily).")
    parser.add_argument("--catchup", action="store_true", help="Skip strict daily file validation (use when catching up multiple missed days - ensure at least one bhavcopy and latest reference files are present).")
    args = parser.parse_args()

    if not args.catchup:
        validate_daily_folder()
    else:
        print("Catch-up mode: skipping strict daily validation. Full history rebuild will incorporate all bhavcopies and latest references found in daily/ + archive.")

    try:
        build_database()
    except FileNotFoundError as exc:
        print()
        print("Update failed due to missing daily files:")
        print(exc)
        print()
        print("If you are catching up after missed uploads, run this script with --catchup.")
        sys.exit(1)
