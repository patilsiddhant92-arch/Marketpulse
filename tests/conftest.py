from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "Scripts"
APP = ROOT / "App"
for path in (ROOT, SCRIPTS, APP):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
