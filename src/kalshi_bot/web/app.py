"""Operator dashboard (spec: operator-dashboard, tasks.md §9).

FastAPI + Jinja2 + HTMX, no build step. Binds to localhost by default; set
`DASHBOARD_AUTH_SECRET` before exposing beyond loopback (tasks.md 9.6) — that
check happens in `scripts/start_dashboard.py`, not here, since "bind address"
is a deployment concern.

Scope note (2026-09-05): built ahead of §4-§7 per explicit reprioritization.
Positions/orders/brackets/funding/liquidation views have no live data source
yet and render as placeholders; everything else here (backtest runs, signals
including HOLDs, equity curve, data coverage, kill switch) is real and reads
the existing schema.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from kalshi_bot.config.settings import get_settings
from kalshi_bot.storage import create_all_tables, get_engine, get_session_factory
from kalshi_bot.web import queries
from kalshi_bot.web.control_state import get_control_panel

WEB_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))


def create_app() -> FastAPI:
    app = FastAPI(title="Kalshi Bot Dashboard")
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

    settings = get_settings()
    engine = get_engine(settings)
    create_all_tables(engine)
    session_factory = get_session_factory(engine)
    panel = get_control_panel()

    def _coverage_refresh_loop() -> None:
        # Full-table-scan coverage report over 17M+ candle rows takes ~60-90s;
        # compute it off the request path so no page load is stuck waiting on
        # it (see queries.py), refreshing periodically so it doesn't go stale
        # forever after the TTL passes.
        while True:
            with session_factory() as warm_session:
                queries.refresh_coverage_cache(warm_session)
            time.sleep(queries.COVERAGE_CACHE_TTL_S)

    threading.Thread(target=_coverage_refresh_loop, daemon=True).start()

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        with session_factory() as session:
            run = queries.latest_backtest_run(session)
            signals = queries.recent_signals(session, backtest_run_id=run.id if run else None)
            coverage = queries.cached_btc_coverage()
            equity = (
                queries.equity_curve(session, run.id, settings.bankroll_total_usd) if run else []
            )
            validation = queries.latest_validation_status(session)
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "control": panel.snapshot(),
                "run": run,
                "signals": signals,
                "coverage": coverage,
                "equity": equity,
                "validation": validation,
                "paper_trading": settings.paper_trading,
            },
        )

    @app.get("/runs", response_class=HTMLResponse)
    def runs(request: Request) -> HTMLResponse:
        with session_factory() as session:
            all_runs = queries.recent_backtest_runs(session)
        return templates.TemplateResponse(request, "runs.html", {"runs": all_runs})

    @app.post("/control/arm", response_class=HTMLResponse)
    def arm(request: Request) -> HTMLResponse:
        # No live trading process exists yet (§4-§7) — arming records operator
        # intent honestly without pretending a bot is now running.
        state = panel.arm()
        return templates.TemplateResponse(request, "_control_status.html", {"control": state})

    @app.post("/control/kill", response_class=HTMLResponse)
    def kill(request: Request) -> HTMLResponse:
        state = panel.kill()
        return templates.TemplateResponse(request, "_control_status.html", {"control": state})

    return app
