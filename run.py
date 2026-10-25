"""Start the Strategy Evolution Lab locally: python run.py  (then open http://127.0.0.1:8000)."""
import argparse
import threading
import webbrowser
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

import uvicorn  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--reload", action="store_true")
    a = ap.parse_args()
    url = f"http://{a.host}:{a.port}"
    print(f"Vizual NN lab -> {url}")
    if not a.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run("lab.server:app", host=a.host, port=a.port, reload=a.reload)
