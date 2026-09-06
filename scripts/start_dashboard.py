"""Launch the operator dashboard and open it in a browser.

Trading always starts stopped (tasks.md 9.2) — opening this dashboard is
never the same act as risking money; arming is an explicit click in the UI.

Binds to 127.0.0.1 by default (tasks.md 9.6). Passing --host to bind beyond
loopback requires DASHBOARD_AUTH_SECRET to be set, since nothing here
implements request auth yet — refuse to expose an unauthenticated dashboard
to the network.

Usage:
  uv run python scripts/start_dashboard.py
  uv run python scripts/start_dashboard.py --port 8080
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import uvicorn  # noqa: E402

from kalshi_bot.config.settings import get_settings  # noqa: E402
from kalshi_bot.web.app import create_app  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    if args.host not in ("127.0.0.1", "localhost"):
        settings = get_settings()
        if settings.dashboard_auth_secret is None:
            print(
                f"Refusing to bind {args.host}: set DASHBOARD_AUTH_SECRET before "
                "exposing the dashboard beyond loopback (tasks.md 9.6)."
            )
            raise SystemExit(1)

    url = f"http://{args.host}:{args.port}/"
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    print(f"Kalshi Bot Dashboard: {url}  (trading starts stopped)")
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
