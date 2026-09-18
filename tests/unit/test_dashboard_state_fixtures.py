"""The dashboard state fixtures really are in the states they claim
(`trader-dashboard-experience` task 1.4).

A fixture that quietly stops representing its scenario is worse than no
fixture: every test built on it keeps passing while asserting nothing. These
tests pin each fixture to the observable property that makes it useful, using
the real query layer wherever one exists.

They also lock in three gaps the audit found, so that a later change which
closes a gap fails here loudly instead of silently invalidating the reasoning
in `audit.md`:

- `simulated_trades` has no run/account key (§1.4)
- an unmarked position yields no unrealized valuation (§1.1)
- there is no order-lifecycle table (§1.4)
"""

from __future__ import annotations

import time

from sqlalchemy import desc, inspect, select
from tests.unit.conftest_dashboard_states import make_simulated_trade

from kalshi_bot.storage import PaperAuditEvent, PaperRun, SimulatedTrade
from kalshi_bot.web.queries import (
    capture_feeds,
    paper_runs_overview,
    perp_positions_view,
    strategy_lab_comparison,
)

BRTI_FEED = "BRTI (Bitcoin index)"


def _feed(session, name: str = BRTI_FEED):
    return next(f for f in capture_feeds(session) if f.name == name)


# --- empty / fresh / stale -------------------------------------------------


def test_empty_state_has_no_runs_and_no_feed_rows(empty_state):
    assert paper_runs_overview(empty_state) == []
    assert _feed(empty_state).rows == 0
    # "empty" must be distinguishable from "stale": a first launch has no data,
    # it does not have old data.
    assert _feed(empty_state).status == "empty"


def test_fresh_state_is_live_with_a_running_run(fresh_state):
    runs = paper_runs_overview(fresh_state)
    assert [r.run_id for r in runs] == ["fresh-1"]
    assert runs[0].decisions == 1

    feed = _feed(fresh_state)
    assert feed.rows > 0
    assert feed.status == "live"
    assert feed.age_s is not None and feed.age_s < 60


def test_stale_state_is_stale_but_still_has_data(stale_state):
    feed = _feed(stale_state)
    assert feed.rows > 0, "stale is not the same as empty — the rows must exist"
    assert feed.status == "stale"
    assert feed.age_s is not None and feed.age_s > 0

    # The run itself still exists; it is the *data* that is old.
    assert [r.run_id for r in paper_runs_overview(stale_state)] == ["stale-1"]


# --- partial (missing mark) ------------------------------------------------


def test_partial_state_position_has_no_mark_so_valuation_is_unavailable(partial_state):
    positions = perp_positions_view(partial_state)
    assert len(positions) == 1
    pos = positions[0]

    # The position is real and open...
    assert pos.status == "open"
    assert pos.entry_price == 60_000.0
    # ...but it has no valuation, so every mark-dependent number is None.
    # None here must mean "unavailable", never 0.
    assert pos.latest_mark is None
    assert pos.liquidation_distance_pct is None
    assert pos.plan_progress_pct is None
    # Realized P&L is genuinely unknown while open, which is a different
    # kind of missing from "we have no mark".
    assert pos.realized_pnl_usd is None


def test_partial_state_realized_results_remain_visible(partial_state):
    """The spec requires available realized results to stay visible even when
    unrealized is incomplete. Fees and funding are recorded, so they must be
    readable numbers rather than None."""
    pos = perp_positions_view(partial_state)[0]
    assert pos.funding_pnl_usd == 0.0
    assert pos.fee_usd == 0.0


# --- error -----------------------------------------------------------------


def test_error_state_surfaces_a_reason_and_a_blocked_asset(error_state):
    runs = paper_runs_overview(error_state)
    assert len(runs) == 1
    run = runs[0]

    assert run.status == "failed"
    assert run.blocked_fill_reasons == {"BTC": "reconstructed_data_not_admissible"}
    # Decisions recorded but nothing could fill: an explained state, not a
    # malfunction (queries.PaperRunSummary.decisions_without_fills).
    assert run.fills == 0


# --- duplicate paper capital ----------------------------------------------


def test_duplicate_capital_yields_two_separate_rows(duplicate_paper_capital):
    fx = duplicate_paper_capital
    rows = {r.run_id: r for r in strategy_lab_comparison(fx.session)}

    assert set(rows) == {"dup-a", "dup-b"}, "each account must remain its own row"
    assert rows["dup-a"].strategy_id == "trend_scalp"
    assert rows["dup-b"].strategy_id == "level_break"

    # `_run_net_pnl` sums realized + funding - fee per run (queries.py:1155-1158).
    # dup-a:  120.0 + (-3.0) - 2.0 = 115.0
    # dup-b: -45.0 +   1.5  - 2.0 = -45.5
    assert rows["dup-a"].net_pnl_usd == 115.0
    assert rows["dup-b"].net_pnl_usd == -45.5

    # The sum exists arithmetically but must never be presented as one funded
    # portfolio: both accounts drew on the SAME simulated $1,000.
    combined_capital_if_summed = fx.starting_capital_usd * 2
    assert combined_capital_if_summed == 2_000.0
    assert fx.starting_capital_usd == 1_000.0


def test_paper_runs_do_not_record_starting_capital(duplicate_paper_capital):
    """Locks in audit.md OPEN-1.

    There is no per-run capital column, which is exactly why two duplicate
    accounts are indistinguishable by capital in the database. If a later
    change adds one, this test fails and the audit's reasoning gets revisited.
    """
    columns = {c.key for c in inspect(PaperRun).mapper.column_attrs}
    assert "starting_capital_usd" not in columns
    assert "account_id" not in columns


# --- partial fills ---------------------------------------------------------


def test_partial_fill_records_less_than_requested(partial_fill_state):
    run = paper_runs_overview(partial_fill_state)[0]
    assert run.run_id == "fill-1"

    pos = perp_positions_view(partial_fill_state)[0]
    assert pos.signed_quantity == 3.0, "the position holds only what actually filled"

    # This run is not admission-blocked; it is size-limited, so the
    # admission-reason map (a different signal) stays empty.
    assert run.blocked_fill_reasons == {}

    # The requested size survives ONLY in the audit payload, because no order
    # table exists to hold it (audit.md §1.4). This is the assertion that
    # actually proves "partial fill" rather than just "a fill happened": it
    # reads the raw payload and checks filled_quantity < requested_quantity,
    # matching the position's own signed_quantity so the two sources agree.
    fill_event = partial_fill_state.execute(
        select(PaperAuditEvent).where(
            PaperAuditEvent.paper_run_id == "fill-1",
            PaperAuditEvent.kind == "fill",
        )
    ).scalar_one()
    assert fill_event.status == "partially_filled"
    assert fill_event.payload["requested_quantity"] == 10.0
    assert fill_event.payload["filled_quantity"] == 3.0
    assert fill_event.payload["filled_quantity"] < fill_event.payload["requested_quantity"]
    assert fill_event.payload["filled_quantity"] == pos.signed_quantity, (
        "the audit payload's filled_quantity must agree with the position's "
        "actual signed_quantity, or the two sources of truth have diverged"
    )


def test_partial_fill_has_no_order_lifecycle_table(partial_fill_state):
    """Locks in audit.md §1.4: fills exist, orders do not.

    `OrderTracker` persists to a JSON file and has no call sites, so there is
    no queryable order lifecycle anywhere in the schema.
    """
    table_names = set(inspect(partial_fill_state.get_bind()).get_table_names())
    assert not {t for t in table_names if "order" in t and "book" not in t}, (
        "an order-lifecycle table now exists; audit.md §1.4 must be revisited"
    )


# --- disconnected runners --------------------------------------------------


def _latest_event_age_s(session, run_id: str) -> int:
    """Age of the most recent audit event for `run_id` — the only liveness
    evidence the schema offers today (audit.md OPEN-5; no heartbeat table
    exists yet). This is deliberately independent of `PaperRun.started_at`:
    a run started 2 hours ago that emitted an event 5 seconds ago is alive,
    and a run started 5 seconds ago whose only event is an hour stale is not
    — start time answers a different question than "is it still running."
    """
    latest = session.execute(
        select(PaperAuditEvent)
        .where(PaperAuditEvent.paper_run_id == run_id)
        .order_by(desc(PaperAuditEvent.observed_at))
        .limit(1)
    ).scalar_one()
    return int(time.time()) - latest.observed_at


def test_running_run_with_stale_heartbeat(disconnected_runner_state):
    fx = disconnected_runner_state
    runs = {r.run_id: r for r in paper_runs_overview(fx.session)}

    running = runs["disc-running"]
    assert running.status == "running"
    assert running.ended_at is None

    # Process state says running, but its most recent audit event — the only
    # liveness evidence the schema offers — is STALE_AGE_S old, not merely
    # "some time after start". A status service must not report this as
    # healthy purely because status == running; it must look at the
    # heartbeat/event recency, which is exactly what this asserts.
    last_event_age = _latest_event_age_s(fx.session, "disc-running")
    assert last_event_age >= fx.stale_age_s, (
        "the fixture's own liveness evidence (its latest event) must actually "
        "be stale, not just old relative to run start"
    )


def test_completed_run_still_emitting_events(disconnected_runner_state):
    fx = disconnected_runner_state
    runs = {r.run_id: r for r in paper_runs_overview(fx.session)}

    completed = runs["disc-completed"]
    assert completed.status == "completed"
    assert completed.ended_at is not None
    # Yet it recorded a decision — the inverse contradiction. Both directions
    # must be representable so the UI can show "unknown" rather than guessing.
    assert completed.decisions == 1
    # And that event is fresh, not merely present — the contradiction is
    # "completed, but something is emitting events right now", not "completed,
    # with old history". A status service reading only `ended_at` would call
    # this healthy-and-stopped; the recency check is what actually surfaces
    # the disagreement.
    last_event_age = _latest_event_age_s(fx.session, "disc-completed")
    assert last_event_age < fx.stale_age_s


# --- ledger identity gap ---------------------------------------------------


def test_simulated_trades_cannot_be_attributed_to_a_run(dashboard_session):
    """Locks in audit.md §1.4 / OPEN-1.

    `simulated_trades` has no `paper_run_id`, so prediction P&L cannot be
    scoped to an account today. `queries._run_net_pnl` documents the same
    limitation in its own comment.
    """
    make_simulated_trade(dashboard_session)
    dashboard_session.commit()

    columns = {c.key for c in inspect(SimulatedTrade).mapper.column_attrs}
    assert "paper_run_id" not in columns
    assert "account_id" not in columns
    # The only run-ish key is backtest_run_id, which is null for paper rows.
    row = dashboard_session.execute(select(SimulatedTrade)).scalar_one()
    assert row.mode == "paper"
    assert row.backtest_run_id is None
