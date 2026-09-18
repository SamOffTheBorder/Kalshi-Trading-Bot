"""Launch the operator dashboard and open it in a browser.

Trading always starts stopped (tasks.md 9.2) — opening this dashboard is
never the same act as risking money; arming is an explicit click in the UI.

Binds to 127.0.0.1 by default. Non-loopback access requires TLS and a secret.
Plain HTTP is only supported on loopback.

Usage:
  uv run python scripts/start_dashboard.py
  uv run python scripts/start_dashboard.py --port 8080
  uv run python scripts/start_dashboard.py --host 192.168.1.20 \
      --tls-certfile cert.pem --tls-keyfile key.pem
"""

from __future__ import annotations

import argparse
import secrets
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
    parser.add_argument("--tls-certfile", type=Path)
    parser.add_argument("--tls-keyfile", type=Path)
    args = parser.parse_args()

    loopback = args.host in ("127.0.0.1", "localhost")
    settings = get_settings()
    if not loopback:
        if settings.dashboard_auth_secret is None:
            print(
                f"Refusing to bind {args.host}: set DASHBOARD_AUTH_SECRET before "
                "exposing the dashboard beyond loopback (tasks.md 9.6)."
            )
            raise SystemExit(1)
        if not args.tls_certfile or not args.tls_keyfile:
            print(
                f"Refusing to bind {args.host}: non-loopback dashboard access requires "
                "--tls-certfile and --tls-keyfile."
            )
            raise SystemExit(1)

    bootstrap_token = secrets.token_urlsafe(32) if loopback else None
    scheme = "https" if not loopback else "http"
    url = (
        f"{scheme}://{args.host}:{args.port}/_auth/bootstrap#{bootstrap_token}"
        if bootstrap_token
        else f"{scheme}://{args.host}:{args.port}/login"
    )
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    print(f"Kalshi Bot Dashboard: {scheme}://{args.host}:{args.port}/  (trading starts stopped)")
    uvicorn.run(
        create_app(bootstrap_token=bootstrap_token, secure_cookies=not loopback),
        host=args.host,
        port=args.port,
        log_level="warning",
        ssl_certfile=str(args.tls_certfile) if args.tls_certfile else None,
        ssl_keyfile=str(args.tls_keyfile) if args.tls_keyfile else None,
    )


if __name__ == "__main__":
    main()
