"""Isolated read-model state fixtures for the trader dashboard
(`trader-dashboard-experience` task 1.4).

Every scenario the four capability specs name a behaviour for needs a database
that actually *is* in that state — otherwise a test asserting "shows
unavailable" passes against a database that was simply empty for an unrelated
reason. These fixtures build each state explicitly, from the real ORM models,
in a throwaway in-memory SQLite database.

Conventions follow the existing dashboard tests
(`test_dashboard_paper_runs.py`, `test_dashboard_strategy_lab.py`):
`create_engine("sqlite://")` + `Base.metadata.create_all`, one session per test,
nothing written to the operator's real database and no process started.

Fixture -> the spec scenario it exists to serve:

- ``empty_state``              trader-workspace "First launch without records"
- ``fresh_state``              freshness `live` (FeedHealth.status)
- ``stale_state``              trader-workspace "Refresh failure" / stale source
- ``partial_state``            trader-portfolio-review "Missing position mark"
- ``error_state``              a recorded failure with a reason
- ``duplicate_paper_capital``  trader-portfolio-review "Compare duplicate paper capital"
- ``partial_fill_state``       trader-portfolio-review "Fill without order lifecycle"
- ``disconnected_runner_state`` trader-operations-workflow "Intent armed without process"

Audit context: `openspec/changes/trader-dashboard-experience/audit.md` §4.2.
Several fixtures deliberately encode a *gap* found by that audit (no stored
capital per run, no mark timestamp, no order lifecycle table). They are built to
stay honest about the gap rather than fake a column that does not exist.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from kalshi_bot.storage import (
    Base,
    BRTIObservation,
    PaperAuditEvent,
    PaperRun,
    PerpPaperEvent,
    PerpPaperPosition,
    SimulatedTrade,
)
from kalshi_bot.web.queries import BTC_INDEX_SOURCE, FEED_STALE_FACTOR

# `capture_feeds` declares the BRTI index feed with a 60s expected interval
# (`queries.py:714-720`), and `FeedHealth.status` calls it stale past
# FEED_STALE_FACTOR * that interval. Anchor the fixtures to the same constants
# rather than to magic numbers: if the cadence policy changes these fixtures
# follow it instead of silently drifting into the wrong state.
BRTI_EXPECTED_INTERVAL_S = 60
STALE_AGE_S = BRTI_EXPECTED_INTERVAL_S * (FEED_STALE_FACTOR + 1)


@pytest.fixture
def dashboard_session() -> Session:
    """A fresh, isolated, in-memory database for one test."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


# --------------------------------------------------------------------------
# builders — small and explicit; a fixture should read as the state it names
# --------------------------------------------------------------------------


def make_run(
    session: Session,
    run_id: str,
    *,
    domain: str = "prediction",
    mode: str = "paper",
    status: str = "completed",
    started_at: int | None = None,
    ended_at: int | None = None,
    strategy_id: str | None = "trend_scalp",
    gate: str | None = "never_gated",
) -> PaperRun:
    """One paper run.

    Note (audit.md §1.0): there is no `starting_capital_usd` column on
    `paper_runs`. Capital comes from `settings.bankroll_total_usd` at process
    start and is not recorded per run. `duplicate_paper_capital` documents the
    consequence rather than inventing the column.
    """
    started = int(time.time()) - 3_600 if started_at is None else started_at
    run = PaperRun(
        id=run_id,
        domain=domain,
        mode=mode,
        asset_ids=["BTC"],
        started_at=started,
        ended_at=ended_at,
        status=status,
        config_fingerprint="fixture",
        strategy_id=strategy_id,
        strategy_config_version=f"{strategy_id}-v1" if strategy_id else None,
        strategy_gate_status=gate,
    )
    session.add(run)
    session.flush()
    return run


def make_audit_event(
    session: Session,
    run_id: str,
    *,
    domain: str = "prediction",
    kind: str = "decision",
    status: str = "hold",
    reason: str | None = None,
    observed_at: int | None = None,
    payload: dict | None = None,
    asset_id: str | None = "BTC",
) -> PaperAuditEvent:
    event = PaperAuditEvent(
        paper_run_id=run_id,
        kind=kind,
        domain=domain,
        asset_id=asset_id,
        observed_at=int(time.time()) if observed_at is None else observed_at,
        status=status,
        reason=reason,
        payload=payload or {},
    )
    session.add(event)
    session.flush()
    return event


def make_brti(session: Session, *, age_s: int, count: int = 5) -> None:
    """`count` BRTI observations whose newest row is `age_s` seconds old.

    Uses the causal pair the codebase standardises on (audit.md §1.0):
    `observed_at` is source event time, `available_at` is when the bot could
    first have used it.
    """
    now = int(time.time())
    for i in range(count):
        observed = now - age_s - i
        session.add(
            BRTIObservation(
                observed_at=observed,
                available_at=observed + 1,
                value_dollars="60000.00",
                source=BTC_INDEX_SOURCE,
                fetched_at=observed + 1,
            )
        )
    session.flush()


def make_perp_position(
    session: Session,
    run_id: str,
    *,
    asset_id: str = "BTC",
    ticker: str = "BTC-PERP",
    signed_quantity: float = 1.0,
    entry_price: float = 60_000.0,
    status: str = "open",
    realized_pnl_usd: float | None = None,
    funding_pnl_usd: float = 0.0,
    fee_usd: float = 0.0,
    with_fill_event: bool = True,
    with_mark: float | None = None,
    liquidation_price: float | None = 54_000.0,
) -> PerpPaperPosition:
    """A perp position, optionally with its opening fill and a latest mark.

    `with_mark=None` leaves the position *unmarked* — the "Missing position
    mark" state, where unrealized P&L must render unavailable rather than 0.
    """
    now = int(time.time())
    pos = PerpPaperPosition(
        paper_run_id=run_id,
        asset_id=asset_id,
        market_ticker=ticker,
        signed_quantity=signed_quantity,
        multiplier=0.0001,
        entry_price=entry_price,
        entry_ts=now - 600,
        status=status,
        realized_pnl_usd=realized_pnl_usd,
        funding_pnl_usd=funding_pnl_usd,
        fee_usd=fee_usd,
    )
    session.add(pos)
    session.flush()

    if with_fill_event:
        session.add(
            PerpPaperEvent(
                position_id=pos.id,
                paper_run_id=run_id,
                event_type="fill",
                observed_at=now - 600,
                price=entry_price,
                quantity=signed_quantity,
                liquidation_price=liquidation_price,
                status="filled",
                payload={"bracket": {"stop_loss": 57_000.0, "take_profit": 66_000.0}},
            )
        )
    if with_mark is not None:
        session.add(
            PerpPaperEvent(
                position_id=pos.id,
                paper_run_id=run_id,
                event_type="mark",
                observed_at=now - 30,
                price=with_mark,
                status="ok",
            )
        )
    session.flush()
    return pos


def make_simulated_trade(
    session: Session,
    *,
    ticker: str = "KXBTC15M-TEST",
    side: str = "yes",
    quantity: float = 10.0,
    entry_price_cents: int = 50,
    status: str = "settled_won",
    net_pnl_usd: float | None = 4.0,
    mode: str = "paper",
) -> SimulatedTrade:
    """One prediction-ledger row.

    Note (audit.md §1.4): `simulated_trades` has **no `paper_run_id`**, so these
    rows cannot be attributed to a run. That is the point of
    `duplicate_paper_capital` — the isolation gap is real, not a fixture defect.
    """
    now = int(time.time())
    trade = SimulatedTrade(
        backtest_run_id=None,
        signal_id=None,
        mode=mode,
        market_ticker=ticker,
        side=side,
        quantity=quantity,
        entry_price_cents=entry_price_cents,
        entry_ts=now - 900,
        exit_price_cents=100 if status == "settled_won" else 0,
        exit_ts=now - 60,
        status=status,
        gross_pnl_usd=net_pnl_usd,
        entry_fee_usd=0.35,
        exit_fee_usd=0.0,
        fee_usd=0.35,
        net_pnl_usd=net_pnl_usd,
    )
    session.add(trade)
    session.flush()
    return trade


# --------------------------------------------------------------------------
# state fixtures
# --------------------------------------------------------------------------


@dataclass
class DuplicateCapital:
    """Two runs started from the same simulated bankroll.

    `starting_capital_usd` is carried **on this fixture object, not in the
    database**, because no such column exists (audit.md §1.0 / OPEN-1). A
    comparison view must therefore treat these as two separate accounts and
    must never present $2,000 of funded capital.
    """

    session: Session
    run_a: PaperRun
    run_b: PaperRun
    starting_capital_usd: float


@dataclass
class DisconnectedRunner:
    """Both directions of runner/heartbeat disagreement.

    ``running_no_heartbeat``: run row says `running`, last audit event is old.
    ``heartbeat_no_running``: run row says `completed`, yet events keep arriving.
    """

    session: Session
    running_no_heartbeat: PaperRun
    heartbeat_no_running: PaperRun
    stale_age_s: int


@pytest.fixture
def empty_state(dashboard_session: Session) -> Session:
    """No runs, no trades, no observations — a brand-new installation."""
    return dashboard_session


@pytest.fixture
def fresh_state(dashboard_session: Session) -> Session:
    """A running run with recent decisions and current BRTI observations."""
    make_run(dashboard_session, "fresh-1", status="running", ended_at=None)
    make_audit_event(dashboard_session, "fresh-1", kind="decision", status="hold")
    make_brti(dashboard_session, age_s=0)
    dashboard_session.commit()
    return dashboard_session


@pytest.fixture
def stale_state(dashboard_session: Session) -> Session:
    """Same shape as `fresh_state`, but every observation is far past cadence."""
    make_run(dashboard_session, "stale-1", status="running", ended_at=None)
    make_audit_event(
        dashboard_session,
        "stale-1",
        kind="decision",
        status="hold",
        observed_at=int(time.time()) - STALE_AGE_S,
    )
    make_brti(dashboard_session, age_s=STALE_AGE_S)
    dashboard_session.commit()
    return dashboard_session


@pytest.fixture
def partial_state(dashboard_session: Session) -> Session:
    """An open perp position with **no mark event**.

    Realized P&L is knowable; unrealized is not. Dependent totals must be
    labelled incomplete rather than silently treated as zero
    (trader-portfolio-review "Missing position mark").
    """
    make_run(dashboard_session, "partial-1", domain="perp", status="running", ended_at=None)
    make_perp_position(
        dashboard_session,
        "partial-1",
        status="open",
        realized_pnl_usd=None,
        with_mark=None,
    )
    dashboard_session.commit()
    return dashboard_session


@pytest.fixture
def error_state(dashboard_session: Session) -> Session:
    """A run carrying a recorded failure with a reason, plus a blocked asset.

    The `preflight_passed` payload matches the shape `_blocked_fill_reasons`
    reads (`queries.py:941-956`): admitted, but not permitted to fill.
    """
    make_run(dashboard_session, "error-1", status="failed", ended_at=int(time.time()))
    make_audit_event(
        dashboard_session,
        "error-1",
        kind="reconciliation",
        status="failed",
        reason="unresolved_open_position",
    )
    make_audit_event(
        dashboard_session,
        "error-1",
        kind="preflight",
        status="preflight_passed",
        payload={
            "admissions": [
                {
                    "asset": "BTC",
                    "admitted": True,
                    "may_fill": False,
                    "reason": "reconstructed_data_not_admissible",
                }
            ]
        },
    )
    dashboard_session.commit()
    return dashboard_session


@pytest.fixture
def duplicate_paper_capital(dashboard_session: Session) -> DuplicateCapital:
    """Two experimental accounts, identical simulated starting capital.

    Disjoint perp ledgers so each run's result is independently attributable.
    A comparison must show two rows, never one summed portfolio
    (trader-portfolio-review "Compare duplicate paper capital").
    """
    capital = 1_000.0
    run_a = make_run(dashboard_session, "dup-a", domain="perp", strategy_id="trend_scalp")
    run_b = make_run(dashboard_session, "dup-b", domain="perp", strategy_id="level_break")

    make_perp_position(
        dashboard_session,
        "dup-a",
        ticker="BTC-PERP",
        status="closed",
        realized_pnl_usd=120.0,
        funding_pnl_usd=-3.0,
        fee_usd=2.0,
        with_mark=61_000.0,
    )
    make_perp_position(
        dashboard_session,
        "dup-b",
        ticker="BTC-PERP",
        status="closed",
        realized_pnl_usd=-45.0,
        funding_pnl_usd=1.5,
        fee_usd=2.0,
        with_mark=59_000.0,
    )
    dashboard_session.commit()
    return DuplicateCapital(
        session=dashboard_session,
        run_a=run_a,
        run_b=run_b,
        starting_capital_usd=capital,
    )


@pytest.fixture
def partial_fill_state(dashboard_session: Session) -> Session:
    """A fill for less than the requested quantity, with no order lifecycle.

    `requested_quantity` lives in the audit payload because there is no order
    table to hold it (audit.md §1.4: `OrderTracker` persists to a JSON file and
    has no call sites). The UI must show the fill and state
    "Order lifecycle not recorded" rather than synthesise an order timeline.
    """
    make_run(dashboard_session, "fill-1", domain="perp", status="running", ended_at=None)
    make_perp_position(
        dashboard_session,
        "fill-1",
        signed_quantity=3.0,
        status="open",
        with_mark=60_500.0,
    )
    make_audit_event(
        dashboard_session,
        "fill-1",
        domain="perp",
        kind="fill",
        status="partially_filled",
        reason="insufficient_resting_size",
        payload={"requested_quantity": 10.0, "filled_quantity": 3.0},
    )
    dashboard_session.commit()
    return dashboard_session


@pytest.fixture
def disconnected_runner_state(dashboard_session: Session) -> DisconnectedRunner:
    """Process state and heartbeat disagreeing, in both directions.

    There is no heartbeat table today (audit.md OPEN-5), so "heartbeat" here is
    the recency of the run's most recent audit event — the only liveness
    evidence the schema actually offers.
    """
    now = int(time.time())
    running = make_run(
        dashboard_session,
        "disc-running",
        status="running",
        ended_at=None,
        started_at=now - 7_200,
    )
    make_audit_event(
        dashboard_session,
        "disc-running",
        kind="decision",
        status="hold",
        observed_at=now - STALE_AGE_S,
    )

    completed = make_run(
        dashboard_session,
        "disc-completed",
        status="completed",
        started_at=now - 7_200,
        ended_at=now - 3_600,
    )
    make_audit_event(
        dashboard_session,
        "disc-completed",
        kind="decision",
        status="hold",
        observed_at=now,
    )
    dashboard_session.commit()
    return DisconnectedRunner(
        session=dashboard_session,
        running_no_heartbeat=running,
        heartbeat_no_running=completed,
        stale_age_s=STALE_AGE_S,
    )
