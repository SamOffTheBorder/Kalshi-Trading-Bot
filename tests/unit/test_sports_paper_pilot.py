"""Sports pilot paper adapter + provider adapter (multi-venue-paper-trading
§10.3, §10.5-10.7).

Covers: feasibility-report prerequisite, changed-candidate invalidation,
provider conflicts + resolution rule, post-cutoff evidence exclusion, in-play
rejection, insufficient liquidity / no fillable quote, official Kalshi
settlement, restart recovery, `copy_trading_unsupported`, and provider gap
reporting.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from kalshi_bot.data.sports.evidence import EvidenceCard, SourceAllowlist  # noqa: E402
from kalshi_bot.data.sports.external import ExternalSportsObservation  # noqa: E402
from kalshi_bot.data.sports.provider_adapter import (  # noqa: E402
    MarketMapping,
    ProviderEntitlement,
    ProviderRow,
    build_gap_report,
    detect_conflicts,
    normalize_observation,
)
from kalshi_bot.data.sports.validation import SportsAdmission  # noqa: E402
from kalshi_bot.execution.sports_paper import (  # noqa: E402
    SportsCandidate,
    SportsMarketState,
    SportsPaperAdapter,
    SportsSignal,
    db_sports_settlement_source,
)
from kalshi_bot.storage.db import create_all_tables  # noqa: E402
from kalshi_bot.storage.models import KalshiMarket, SimulatedTrade  # noqa: E402


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    return sessionmaker(bind=engine)


CANDIDATE = SportsCandidate(
    sport="nba",
    market_class="pre_game_moneyline",
    strategy_version="sv1",
    execution_assumptions_hash="hash-abc",
)

ADMITTED = SportsAdmission(
    admitted=True, reason="pass", report_outcome="research_promising", operator_acknowledged=True
)


def _market_state(**overrides) -> SportsMarketState:
    base = dict(
        market_ticker="KXNBA-GSWLAL-GSW",
        series_ticker="KXNBA",
        raw_market={
            "ticker": "KXNBA-GSWLAL-GSW",
            "event_ticker": "KXNBA-GSWLAL",
            "sport": "nba",
            "title": "Warriors vs Lakers - Warriors win",
            "outcome_shape": "binary",
            "settlement_source": "https://nba.com/official",
        },
        raw_series={"sport": "nba"},
        observed_at=1_000,
        close_ts=10_000,
        event_start_ts=9_000,
        in_play=False,
        yes_bid_cents=48,
        yes_ask_cents=52,
        result=None,
    )
    base.update(overrides)
    return SportsMarketState(**base)


def _adapter(
    session, *, admission=ADMITTED, strategy=None, market=None, **kw
) -> SportsPaperAdapter:
    state = market if market is not None else _market_state()
    return SportsPaperAdapter(
        session=session,
        candidate=CANDIDATE,
        admission=admission,
        market_source=lambda _now: state,
        evidence_source=kw.pop("evidence_source", lambda _t, _n: []),
        settlement_source=kw.pop("settlement_source", lambda _t: None),
        starting_cash_usd=1_000.0,
        strategy=strategy or (lambda _s: SportsSignal(action="hold")),
        **kw,
    )


# --------------------------------------------------------------------------
# Admission prerequisite / candidate identity
# --------------------------------------------------------------------------


def test_non_promising_report_blocks_every_entry(session_factory):
    with session_factory() as s:
        blocked = SportsAdmission(False, "research_not_promising", "insufficient_data", False)
        adapter = _adapter(
            s,
            admission=blocked,
            strategy=lambda _s: SportsSignal(action="buy", side="yes", limit_price_cents=60),
        )
        decision = adapter.evaluate("NBA", now_ts=1_000, may_fill=True)
    assert decision.action == "blocked"
    assert decision.status == "admission_blocked"
    assert "research_not_promising" in decision.reason


def test_changed_candidate_is_a_different_identity():
    changed = SportsCandidate("nba", "pre_game_moneyline", "sv2", "hash-abc")
    assert not CANDIDATE.matches(changed)
    assert CANDIDATE.matches(
        SportsCandidate("nba", "pre_game_moneyline", "sv1", "hash-abc")
    )


# --------------------------------------------------------------------------
# Classification / in-play / freshness
# --------------------------------------------------------------------------


def test_in_play_market_is_rejected_before_strategy(session_factory):
    with session_factory() as s:
        adapter = _adapter(
            s,
            market=_market_state(in_play=True),
            strategy=lambda _s: SportsSignal(action="buy", side="yes", limit_price_cents=60),
        )
        decision = adapter.evaluate("NBA", now_ts=1_000, may_fill=True)
    assert decision.status == "in_play_rejected"


def test_event_already_started_is_rejected(session_factory):
    with session_factory() as s:
        adapter = _adapter(s, market=_market_state(event_start_ts=500))
        decision = adapter.evaluate("NBA", now_ts=1_000, may_fill=True)
    assert decision.status == "in_play_rejected"


def test_parlay_market_is_classification_rejected(session_factory):
    with session_factory() as s:
        parlay = _market_state(
            raw_market={
                "ticker": "KXNBA-PARLAY-1",
                "event_ticker": "KXNBA-PARLAY",
                "sport": "nba",
                "title": "Same game parlay",
                "settlement_source": "x",
            }
        )
        adapter = _adapter(s, market=parlay)
        decision = adapter.evaluate("NBA", now_ts=1_000, may_fill=True)
    assert decision.status == "classification_rejected"


def test_stale_quote_is_rejected(session_factory):
    with session_factory() as s:
        # Pre-game (event far in the future) but the quote itself is stale.
        adapter = _adapter(
            s,
            market=_market_state(observed_at=1_000, event_start_ts=1_000_000, close_ts=1_001_000),
            max_data_age_seconds=60,
        )
        decision = adapter.evaluate("NBA", now_ts=5_000, may_fill=True)
    assert decision.status == "stale_quote"


# --------------------------------------------------------------------------
# Evidence causality + conflicts
# --------------------------------------------------------------------------


def _card(claim, provider, content, *, publication_at, available_at):
    return EvidenceCard(
        market_ticker="KXNBA-GSWLAL-GSW",
        provider=provider,
        endpoint_url=f"https://{provider}.example/api",
        claim=claim,
        publication_at=publication_at,
        available_at=available_at,
        retrieved_at=available_at,
        raw_content=content,
        status="usable",
    )


def test_post_cutoff_evidence_is_excluded_from_the_decision(session_factory):
    with session_factory() as s:
        late = _card("starting_lineup", "provA", "lineup", publication_at=5_000, available_at=5_000)
        adapter = _adapter(
            s,
            required_claims=("starting_lineup",),
            evidence_source=lambda _t, _n: [late],
            strategy=lambda _s: SportsSignal(action="buy", side="yes", limit_price_cents=60),
        )
        decision = adapter.evaluate("NBA", now_ts=1_000, may_fill=True)
    assert decision.status == "evidence_blocked"
    assert "missing_causal_evidence" in decision.reason


def test_conflicting_evidence_without_resolution_rule_blocks_entry(session_factory):
    with session_factory() as s:
        a = _card("starting_lineup", "provA", "lineup-A", publication_at=100, available_at=100)
        b = _card("starting_lineup", "provB", "lineup-B", publication_at=100, available_at=100)
        adapter = _adapter(
            s,
            required_claims=("starting_lineup",),
            evidence_source=lambda _t, _n: [a, b],
            strategy=lambda _s: SportsSignal(action="buy", side="yes", limit_price_cents=60),
        )
        decision = adapter.evaluate("NBA", now_ts=1_000, may_fill=True)
    assert decision.status == "evidence_blocked"
    assert "evidence_conflicted" in decision.reason


def test_conflict_resolved_by_priority_allows_entry(session_factory):
    with session_factory() as s:
        a = _card("starting_lineup", "provA", "lineup-A", publication_at=100, available_at=100)
        b = _card("starting_lineup", "provB", "lineup-B", publication_at=100, available_at=100)
        adapter = _adapter(
            s,
            required_claims=("starting_lineup",),
            conflict_resolution_priority=("provA",),
            evidence_source=lambda _t, _n: [a, b],
            strategy=lambda _s: SportsSignal(action="buy", side="yes", limit_price_cents=60),
        )
        decision = adapter.evaluate("NBA", now_ts=1_000, may_fill=True)
    assert decision.status == "filled"


# --------------------------------------------------------------------------
# Fills / liquidity / copy trading / settlement / restart
# --------------------------------------------------------------------------


def test_no_fillable_quote_is_rejected(session_factory):
    with session_factory() as s:
        adapter = _adapter(
            s,
            market=_market_state(yes_ask_cents=None),
            strategy=lambda _s: SportsSignal(action="buy", side="yes", limit_price_cents=60),
        )
        decision = adapter.evaluate("NBA", now_ts=1_000, may_fill=True)
    assert decision.status == "no_fillable_quote"


def test_limit_below_quote_is_not_filled(session_factory):
    with session_factory() as s:
        adapter = _adapter(
            s,
            strategy=lambda _s: SportsSignal(action="buy", side="yes", limit_price_cents=40),
        )
        decision = adapter.evaluate("NBA", now_ts=1_000, may_fill=True)
    assert decision.status == "no_fillable_quote"


def test_copy_trade_instruction_is_rejected(session_factory):
    with session_factory() as s:
        adapter = _adapter(
            s,
            strategy=lambda _s: SportsSignal(
                action="buy", side="yes", limit_price_cents=60,
                attributed_to_other_trader=True,
            ),
        )
        decision = adapter.evaluate("NBA", now_ts=1_000, may_fill=True)
    assert decision.status == "copy_trading_unsupported"


def test_successful_pilot_fill(session_factory):
    with session_factory() as s:
        adapter = _adapter(
            s,
            strategy=lambda _s: SportsSignal(action="buy", side="yes", limit_price_cents=60),
        )
        filled = adapter.evaluate("NBA", now_ts=1_000, may_fill=True)
        s.commit()
        assert filled.status == "filled"
        trades = list(s.execute(select(SimulatedTrade)).scalars())
        assert len(trades) == 1 and trades[0].entry_price_cents == 52


def test_shadow_mode_records_would_fill_without_a_trade(session_factory):
    with session_factory() as s:
        shadow = _adapter(
            s,
            strategy=lambda _s: SportsSignal(action="buy", side="yes", limit_price_cents=60),
        )
        decision = shadow.evaluate("NBA", now_ts=1_000, may_fill=False)
        s.commit()
        assert decision.status == "shadow_would_fill"
        assert not list(s.execute(select(SimulatedTrade)).scalars())


def test_restart_settles_from_official_kalshi_result(session_factory):
    with session_factory() as seed:
        seed.add(
            KalshiMarket(
                ticker="KXNBA-OLD-GSW",
                series_ticker="KXNBA",
                open_ts=0,
                close_ts=500,
                status="settled",
                result="yes",
            )
        )
        seed.add(
            SimulatedTrade(
                mode="paper",
                market_ticker="KXNBA-OLD-GSW",
                side="yes",
                quantity=1,
                entry_price_cents=50,
                entry_ts=100,
                status="open",
                entry_fee_usd=0.02,
            )
        )
        seed.commit()

    with session_factory() as s:
        adapter = SportsPaperAdapter(
            session=s,
            candidate=CANDIDATE,
            admission=ADMITTED,
            market_source=lambda _n: None,
            evidence_source=lambda _t, _n: [],
            settlement_source=db_sports_settlement_source(s),
            starting_cash_usd=1_000.0,
        )
        outcome = adapter.reconcile("NBA")
        s.commit()
        assert outcome.resolved is True
        row = s.execute(
            select(SimulatedTrade).where(SimulatedTrade.market_ticker == "KXNBA-OLD-GSW")
        ).scalar_one()
        assert row.status == "settled_won"


def test_restart_blocks_new_entries_while_unresolved(session_factory):
    with session_factory() as seed:
        seed.add(
            SimulatedTrade(
                mode="paper",
                market_ticker="KXNBA-PENDING",
                side="yes",
                quantity=1,
                entry_price_cents=50,
                entry_ts=100,
                status="open",
                entry_fee_usd=0.02,
            )
        )
        seed.commit()
    with session_factory() as s:
        adapter = _adapter(s, settlement_source=lambda _t: None)
        outcome = adapter.reconcile("NBA")
    assert outcome.resolved is False
    assert "official_result" in outcome.reason


# --------------------------------------------------------------------------
# Provider adapter (§10.3)
# --------------------------------------------------------------------------


ALLOWLIST = SourceAllowlist(
    providers=frozenset({"provA", "provB"}),
    domains=frozenset({"example.com"}),
)
ENTITLEMENT = ProviderEntitlement(
    provider="provA",
    terms_url="https://example.com/terms",
    retention_days=30,
    attribution_required=True,
    max_requests_per_minute=30,
    historical_snapshots=True,
)
MAPPING = MarketMapping(
    provider_event_id="ev1",
    provider_market_id="mk1",
    kalshi_market_ticker="KXNBA-GSWLAL-GSW",
    kalshi_series_ticker="KXNBA",
)


def _obs(
    provider="provA", url="https://data.example.com/api", *, observed_at=100, available_at=100
):
    return ExternalSportsObservation(
        provider=provider,
        endpoint=url,
        observed_at=observed_at,
        available_at=available_at,
        value={"win_prob": 0.6},
        provenance={"raw": "x"},
    )


def test_provider_normalize_flags_disallowed_source():
    row = normalize_observation(
        _obs(provider="provX"),
        claim="win_prob",
        parser_version="p1",
        allowlist=ALLOWLIST,
        entitlement=ENTITLEMENT,
        mapping=MAPPING,
        raw_content="{}",
        now_ts=200,
    )
    assert row.status == "disallowed_source"


def test_provider_normalize_flags_unmapped_and_missing_entitlement():
    unmapped = normalize_observation(
        _obs(), claim="win_prob", parser_version="p1", allowlist=ALLOWLIST,
        entitlement=ENTITLEMENT, mapping=None, raw_content="{}", now_ts=200,
    )
    assert unmapped.status == "unmapped"
    no_ent = normalize_observation(
        _obs(), claim="win_prob", parser_version="p1", allowlist=ALLOWLIST,
        entitlement=None, mapping=MAPPING, raw_content="{}", now_ts=200,
    )
    assert no_ent.status == "parse_error"


def test_provider_conflicts_and_priority_resolution():
    rows = [
        ProviderRow("provA", "u", "win_prob", {"v": 1}, 100, 100, 110, "{}", "p1",
                    "KXNBA-GSWLAL-GSW", "parsed"),
        ProviderRow("provB", "u", "win_prob", {"v": 2}, 100, 100, 110, "{}", "p1",
                    "KXNBA-GSWLAL-GSW", "parsed"),
    ]
    unresolved = detect_conflicts(rows, decision_ts=200)
    assert unresolved[0].conflicted is True
    resolved = detect_conflicts(rows, decision_ts=200, resolution_priority=("provB",))
    assert resolved[0].conflicted is False
    assert resolved[0].resolved_provider == "provB"


def test_provider_conflict_ignores_non_causal_rows():
    rows = [
        ProviderRow("provA", "u", "win_prob", {"v": 1}, 100, 100, 110, "{}", "p1",
                    "KXNBA-GSWLAL-GSW", "parsed"),
        ProviderRow("provB", "u", "win_prob", {"v": 2}, 500, 500, 510, "{}", "p1",
                    "KXNBA-GSWLAL-GSW", "parsed"),
    ]
    # decision at 200: provB's row is not yet causal -> no conflict.
    out = detect_conflicts(rows, decision_ts=200)
    assert out[0].conflicted is False


def test_provider_gap_report_lists_missing_intervals_without_filling():
    rows = [
        ProviderRow("provA", "u", "win_prob", {}, t, t, t, "{}", "p1",
                    "KXNBA-GSWLAL-GSW", "parsed")
        for t in (0, 60, 240)  # missing the 120-180 and 180-240 buckets
    ]
    report = build_gap_report(
        rows,
        market_ticker="KXNBA-GSWLAL-GSW",
        claim="win_prob",
        window_start_ts=0,
        window_end_ts=300,
        expected_interval_s=60,
    )
    assert report.has_gaps
    assert (120, 180) in report.missing_intervals
    assert (180, 240) in report.missing_intervals
    assert report.observed_count == 3
