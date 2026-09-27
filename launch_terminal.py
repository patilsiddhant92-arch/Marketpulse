"""
MarketPulse 3.0 Terminal Launcher (Option A)
Starts the FastAPI analytical server with integrated React terminal interface
and opens it in your default web browser.
"""
import sys
import webbrowser
import threading
import time
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn

def open_browser():
    time.sleep(1.2)
    print("\n⚡ Opening MarketPulse 3.0 Terminal in your browser: http://127.0.0.1:8000")
    webbrowser.open("http://127.0.0.1:8000")

if __name__ == "__main__":
    print("=" * 70)
    print("🚀 Starting MarketPulse 3.0 Terminal (FastAPI + DuckDB + React 19)")
    print("=" * 70)
    
    # Auto-launch browser tab
    threading.Thread(target=open_browser, daemon=True).start()
    
    # Run Uvicorn server
    uvicorn.run("App.api.server:app", host="127.0.0.1", port=8000, reload=False, log_level="info")
