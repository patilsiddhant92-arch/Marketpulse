"""Write frontend/openapi.json from the API v2 app's OpenAPI schema.

Usage:  .venv\\Scripts\\python.exe Scripts\\export_openapi.py [--check]

The frontend generates `src/api/types.gen.ts` from this file (`npm run gen:api`,
openapi-typescript). `--check` exits 1 when the committed file is out of date.
Only the v2 routes are exported (the legacy /api/* endpoints are being retired).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "frontend" / "openapi.json"


def render() -> str:
    from App.api.v2 import create_app

    return json.dumps(create_app().openapi(), indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if frontend/openapi.json is stale")
    args = parser.parse_args()
    text = render()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print(f"{OUT} is out of date; run Scripts/export_openapi.py", file=sys.stderr)
            return 1
        print(f"{OUT} is up to date")
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT} ({len(text):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
