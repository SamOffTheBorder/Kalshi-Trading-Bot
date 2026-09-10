"""Operator dashboard (spec: operator-dashboard, tasks.md §9).

FastAPI + Jinja2, no build step and no JavaScript dependency: the control
buttons are plain form POSTs so the kill switch keeps working with no network
and no CDN reachable.

Binds to localhost by default; set `DASHBOARD_AUTH_SECRET` before exposing
beyond loopback (tasks.md 9.6) — that check lives in
`scripts/start_dashboard.py`, since "bind address" is a deployment concern.

Scope note: positions/orders/brackets/funding views have no live data source
(no trading loop exists yet) and render as explicit placeholders. Everything
else — capture-feed health, validation readiness, backtest runs, signals
including HOLDs, equity, coverage — is real and reads the existing schema.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from kalshi_bot.backtest.promotion_gate import PromotionPolicy
from kalshi_bot.backtest.validation_run import (
    DEFAULT_EMBARGO_SECONDS,
    DEFAULT_TEST_SECONDS,
    DEFAULT_TRAIN_SECONDS,
)
from kalshi_bot.config.settings import get_settings
from kalshi_bot.storage import create_all_tables, get_engine, get_session_factory
from kalshi_bot.web import queries
from kalshi_bot.web.control_state import get_control_panel
from kalshi_bot.web.operations import COMMANDS, CaptureProcess, OperationManager, PaperProcess

WEB_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))


def _humanize_age(seconds: int | None) -> str:
    """ "just now" / "4m ago" / "2h ago" — a raw epoch tells an operator nothing."""
    if seconds is None:
        return "never"
    if seconds < 90:
        return f"{seconds}s ago"
    if seconds < 5_400:
        return f"{seconds // 60}m ago"
    if seconds < 172_800:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86_400}d ago"


def _ts_date(ts: int | None) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d")


def _ts_time(ts: int | None) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts, UTC).strftime("%m-%d %H:%M")


def _equity_sparkline(points: list[queries.EquityPoint]) -> Markup:
    """Inline SVG equity curve.

    Inline rather than a chart library: it keeps the no-JS, no-CDN property,
    and a single series over time needs no more than a polyline.
    """
    values = [p.equity_usd for p in points]
    if len(values) < 2:
        return Markup("")

    width, height, pad = 800.0, 56.0, 4.0
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    step = width / (len(values) - 1)
    coords = [
        (i * step, pad + (height - 2 * pad) * (1.0 - (v - lo) / span)) for i, v in enumerate(values)
    ]
    line = " ".join(f"{x:.2f},{y:.2f}" for x, y in coords)
    area = f"0,{height:.2f} {line} {width:.2f},{height:.2f}"
    up = values[-1] >= values[0]
    stroke = "#3ecf8e" if up else "#f0555a"
    fill = "rgba(62,207,142,0.12)" if up else "rgba(240,85,90,0.12)"

    return Markup(
        f'<svg class="spark" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'preserveAspectRatio="none" role="img" '
        f'aria-label="Equity from {values[0]:.2f} to {values[-1]:.2f} dollars">'
        f'<polygon points="{area}" fill="{fill}"/>'
        f'<polyline points="{line}" fill="none" stroke="{stroke}" '
        f'stroke-width="1.5" vector-effect="non-scaling-stroke"/>'
        f"</svg>"
    )


templates.env.filters["humanize_age"] = _humanize_age
templates.env.filters["ts_date"] = _ts_date
templates.env.filters["ts_time"] = _ts_time
templates.env.filters["equity_sparkline"] = _equity_sparkline


def create_app() -> FastAPI:
    app = FastAPI(title="Kalshi Bot Dashboard")
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

    settings = get_settings()
    engine = get_engine(settings)
    create_all_tables(engine)
    session_factory = get_session_factory(engine)
    panel = get_control_panel()
    operations = OperationManager(Path.cwd())
    paper_process = PaperProcess(Path.cwd())
    capture_process = CaptureProcess(Path.cwd())
    policy = PromotionPolicy()

    fold_geometry = (
        f"{DEFAULT_TRAIN_SECONDS // 86_400}d train / "
        f"{DEFAULT_EMBARGO_SECONDS // 86_400}d embargo / "
        f"{policy.min_folds} x {DEFAULT_TEST_SECONDS // 86_400}d test folds"
    )

    def _readiness(session):
        return queries.validation_readiness(
            session,
            train_seconds=DEFAULT_TRAIN_SECONDS,
            test_seconds=DEFAULT_TEST_SECONDS,
            embargo_seconds=DEFAULT_EMBARGO_SECONDS,
            min_folds=policy.min_folds,
        )

    def _base_context() -> dict:
        return {
            "paper_trading": settings.paper_trading,
            "now_utc": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        }

    def _coverage_refresh_loop() -> None:
        # Full-table-scan coverage over 17M+ candle rows takes ~60-90s; compute
        # it off the request path so no page load waits on it, refreshing
        # periodically so it doesn't go stale forever after the TTL passes.
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
            equity = (
                queries.equity_curve(session, run.id, settings.bankroll_total_usd) if run else []
            )
            context = {
                **_base_context(),
                "active_page": "overview",
                "control": panel.snapshot(),
                "run": run,
                "signals": signals,
                "equity": equity,
                "validation": queries.latest_validation_status(session),
                "feeds": queries.capture_feeds(session),
                "readiness": _readiness(session),
                "fold_geometry": fold_geometry,
                "paper_runs": queries.paper_runs_overview(session),
            }
        return templates.TemplateResponse(request, "index.html", context)

    @app.get("/data", response_class=HTMLResponse)
    def data(request: Request) -> HTMLResponse:
        with session_factory() as session:
            context = {
                **_base_context(),
                "active_page": "data",
                "feeds": queries.capture_feeds(session),
                "sampling": queries.sampling_quality(session),
                "coverage": queries.cached_btc_coverage(),
                "capture_process": capture_process.snapshot(),
            }
        return templates.TemplateResponse(request, "data.html", context)

    @app.get("/markets", response_class=HTMLResponse)
    def markets(request: Request) -> HTMLResponse:
        with session_factory() as session:
            context = {
                **_base_context(),
                "active_page": "markets",
                "areas": queries.market_areas(session),
                "admissions": queries.asset_admissions(session),
            }
        return templates.TemplateResponse(request, "markets.html", context)

    # dashboard area key -> paper-run domain
    area_domain = {
        "sports": "sports",
        "perps": "perp",
        "prediction-markets": "prediction",
    }

    def _area_response(request: Request, area_key: str) -> HTMLResponse:
        domain = area_domain[area_key]
        with session_factory() as session:
            area = next(item for item in queries.market_areas(session) if item.key == area_key)
            admissions = [
                a for a in queries.asset_admissions(session) if a.domain == domain
            ]
            paper_runs = queries.domain_paper_runs(session, domain)
        return templates.TemplateResponse(
            request,
            "market_area.html",
            {
                **_base_context(),
                "active_page": area_key,
                "area": area,
                "admissions": admissions,
                "paper_runs": paper_runs,
            },
        )

    @app.get("/sports", response_class=HTMLResponse)
    def sports(request: Request) -> HTMLResponse:
        return _area_response(request, "sports")

    @app.get("/perps", response_class=HTMLResponse)
    def perps(request: Request) -> HTMLResponse:
        return _area_response(request, "perps")

    @app.get("/prediction-markets", response_class=HTMLResponse)
    def prediction_markets(request: Request) -> HTMLResponse:
        return _area_response(request, "prediction-markets")

    @app.get("/runs", response_class=HTMLResponse)
    def runs(request: Request) -> HTMLResponse:
        with session_factory() as session:
            all_runs = queries.recent_backtest_runs(session)
        return templates.TemplateResponse(
            request,
            "runs.html",
            {**_base_context(), "active_page": "runs", "runs": all_runs},
        )

    @app.get("/operations", response_class=HTMLResponse)
    def operations_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "operations.html",
            {
                **_base_context(),
                "active_page": "operations",
                "operations": operations.snapshot(),
                "operation_names": tuple(COMMANDS),
                "paper_process": paper_process.snapshot(),
            },
        )

    @app.post("/operations/paper/start")
    def start_paper_engine() -> RedirectResponse:
        if not settings.paper_trading:
            raise HTTPException(status_code=409, detail="PAPER_TRADING must be true")
        paper_process.start()
        return RedirectResponse("/operations", status_code=303)

    @app.post("/operations/paper/stop")
    def stop_paper_engine() -> RedirectResponse:
        paper_process.stop()
        return RedirectResponse("/operations", status_code=303)

    @app.post("/operations/capture/start")
    def start_capture_engine() -> RedirectResponse:
        capture_process.start()
        return RedirectResponse("/data", status_code=303)

    @app.post("/operations/capture/stop")
    def stop_capture_engine() -> RedirectResponse:
        capture_process.stop()
        return RedirectResponse("/data", status_code=303)

    @app.post("/operations/{name}")
    def start_operation(name: str) -> RedirectResponse:
        try:
            operations.start(name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown operation") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return RedirectResponse("/operations", status_code=303)

    # Controls are form POSTs and redirect back (POST/redirect/GET) so a
    # refresh never re-submits, and they work without scripting.

    @app.post("/control/arm")
    def arm() -> RedirectResponse:
        # No live-trading process exists yet — arming records operator intent
        # honestly without pretending a bot is now running.
        panel.arm()
        return RedirectResponse("/", status_code=303)

    @app.post("/control/kill")
    def kill() -> RedirectResponse:
        panel.kill()
        return RedirectResponse("/", status_code=303)

    return app
