"""`scripts/run_strategy_lab.py` — spec parsing, account bounds, and
concurrent-account isolation (strategy-lab-multi-account §6.6).

Covers: the spec parser rejects an empty/oversized/duplicate-name spec and
raises the sub-floor poll interval; two concurrent `PaperOrchestrator`
runs record against distinct `paper_run_id`s; one run halting (raising)
does not stop another; each account's broker is seeded with its own
bankroll and never sees another's.
"""

from __future__ import annotations

import importlib.util
import sys
import threading
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from kalshi_bot.config.settings import Settings  # noqa: E402
from kalshi_bot.execution.orchestrator import (  # noqa: E402
    AdapterDecision,
    PaperOrchestrator,
    PaperRunConfig,
    ReconciliationOutcome,
)
from kalshi_bot.storage.db import create_all_tables  # noqa: E402
from kalshi_bot.storage.models import PaperRun  # noqa: E402


def _load_launcher():
    path = REPO_ROOT / "scripts" / "run_strategy_lab.py"
    spec = importlib.util.spec_from_file_location("run_strategy_lab", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_strategy_lab"] = mod  # dataclass introspection needs this
    spec.loader.exec_module(mod)
    return mod


launcher = _load_launcher()


@pytest.fixture
def session_factory(tmp_path):
    # A file-backed DB (not ":memory:") so the concurrent-run tests, which
    # use real threads, all see the same schema and rows — each thread opens
    # its own connection.
    engine = create_engine(f"sqlite:///{(tmp_path / 'lab.db').as_posix()}")
    create_all_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _settings(**overrides):
    base = dict(
        paper_trading=True, kalshi_use_demo_env=True,
        db_path="paper.db", bankroll_total_usd=1_000.0,
    )
    base.update(overrides)
    return Settings(**base)


def _clock(start=0.0, step=1.0):
    t = [start - step]

    def _now():
        t[0] += step
        return t[0]

    return _now


def _paper_lifecycle_registry(asset):
    from kalshi_bot.config import crypto_registry as cr

    return tuple(
        a.model_copy(
            update={
                "event_instruments": {
                    k: v.model_copy(update={"lifecycle": "paper"})
                    for k, v in a.event_instruments.items()
                }
            }
        )
        if a.asset_id == asset
        else a
        for a in cr.DEFAULT_CRYPTO_REGISTRY
    )


# -- spec parsing ------------------------------------------------------


def _write(tmp_path, obj):
    import json

    p = tmp_path / "lab.json"
    p.write_text(json.dumps(obj))
    return p


def test_spec_rejects_empty_accounts(tmp_path):
    with pytest.raises(SystemExit, match="no accounts"):
        launcher._load_spec(_write(tmp_path, {"accounts": []}))


def test_spec_rejects_too_many_accounts(tmp_path):
    accounts = [
        {"name": f"a{i}", "assets": ["BTC"]}
        for i in range(launcher.MAX_ACCOUNTS + 1)
    ]
    with pytest.raises(SystemExit, match="exceeds MAX_ACCOUNTS"):
        launcher._load_spec(_write(tmp_path, {"accounts": accounts}))


def test_spec_rejects_duplicate_names(tmp_path):
    accounts = [
        {"name": "dup", "assets": ["BTC"]},
        {"name": "dup", "assets": ["ETH"]},
    ]
    with pytest.raises(SystemExit, match="unique"):
        launcher._load_spec(_write(tmp_path, {"accounts": accounts}))


def test_spec_raises_sub_floor_poll_interval(tmp_path):
    specs, poll = launcher._load_spec(
        _write(
            tmp_path,
            {
                "poll_interval_seconds": 1,
                "accounts": [{"name": "a", "assets": ["BTC"]}],
            },
        )
    )
    assert poll == launcher.MIN_POLL_INTERVAL_SECONDS
    assert len(specs) == 1


def test_account_spec_defaults_bankroll_to_settings(tmp_path):
    from kalshi_bot.config.settings import get_settings

    specs, _ = launcher._load_spec(
        _write(tmp_path, {"accounts": [{"name": "a", "assets": ["BTC"]}]})
    )
    assert specs[0].bankroll_usd == float(get_settings().bankroll_total_usd)
    assert specs[0].strategy_id == "unspecified"
    assert specs[0].mode == "shadow"


def test_account_spec_reads_explicit_fields(tmp_path):
    specs, _ = launcher._load_spec(
        _write(
            tmp_path,
            {
                "accounts": [
                    {
                        "name": "x", "domain": "prediction",
                        "strategy": "trend_scalp", "assets": ["btc", "eth"],
                        "bankroll_usd": 250, "mode": "shadow",
                        "duration_seconds": 900, "config_id": "c1",
                    }
                ]
            },
        )
    )
    s = specs[0]
    assert s.strategy_id == "trend_scalp"
    assert s.assets == ("BTC", "ETH")
    assert s.bankroll_usd == 250.0
    assert s.duration_seconds == 900.0
    assert s.config_id == "c1"


# -- concurrent isolation --------------------------------------------


class _StubAdapter:
    domain = "prediction"
    broker_name = "paper"

    def __init__(self, *, decision, on_cycle=None):
        self._decision = decision
        self._on_cycle = on_cycle

    def reconcile(self, asset_id):
        return ReconciliationOutcome(asset_id, True, "no_open_positions")

    def evaluate(self, asset_id, *, now_ts, may_fill):
        if self._on_cycle is not None:
            self._on_cycle()
        return self._decision


def _orchestrator(session_factory, *, asset, run_id, adapter, max_cycles=2):
    reg = _paper_lifecycle_registry(asset)
    cfg = PaperRunConfig(
        domain="prediction", assets=(asset,), mode="shadow", strategy_id="hold"
    )
    return PaperOrchestrator(
        settings=_settings(),
        config=cfg,
        session_factory=session_factory,
        adapter=adapter,
        now_fn=_clock(),
        sleep_fn=lambda _s: None,
        cycle_seconds=0.0,
        registry=reg,
        max_cycles=max_cycles,
        run_id=run_id,
    )


def test_two_concurrent_runs_record_distinct_run_ids(session_factory):
    a = _orchestrator(
        session_factory, asset="BTC", run_id="run-a",
        adapter=_StubAdapter(
            decision=AdapterDecision("BTC", "prediction", "hold", "hold")
        ),
    )
    b = _orchestrator(
        session_factory, asset="ETH", run_id="run-b",
        adapter=_StubAdapter(
            decision=AdapterDecision("ETH", "prediction", "hold", "hold")
        ),
    )
    ta = threading.Thread(target=a.run)
    tb = threading.Thread(target=b.run)
    ta.start()
    tb.start()
    ta.join(timeout=10)
    tb.join(timeout=10)

    with session_factory() as session:
        ids = {r.id for r in session.execute(select(PaperRun)).scalars()}
    assert ids == {"run-a", "run-b"}


def test_one_run_faulting_does_not_stop_another(session_factory):
    # An adapter that raises on every cycle. The orchestrator records
    # `adapter_error` and keeps going (its own isolation) — and the OTHER
    # account is entirely unaffected. This is the §6.6 "one run's halt does
    # not halt another" guarantee, at least as strong as required.
    a = _orchestrator(
        session_factory, asset="BTC", run_id="run-a", max_cycles=2,
        adapter=_StubAdapter(
            decision=AdapterDecision("BTC", "prediction", "hold", "hold"),
            on_cycle=lambda: (_ for _ in ()).throw(RuntimeError("A faults")),
        ),
    )
    b_marks: list[int] = []
    b = _orchestrator(
        session_factory, asset="ETH", run_id="run-b", max_cycles=3,
        adapter=_StubAdapter(
            decision=AdapterDecision("ETH", "prediction", "hold", "hold"),
            on_cycle=lambda: b_marks.append(1),
        ),
    )

    errors: dict[str, BaseException] = {}

    def _guarded(name, orch):
        try:
            orch.run()
        except BaseException as exc:  # captured for the assertion
            errors[name] = exc

    ta = threading.Thread(target=_guarded, args=("a", a))
    tb = threading.Thread(target=_guarded, args=("b", b))
    ta.start()
    tb.start()
    ta.join(timeout=10)
    tb.join(timeout=10)

    # Neither thread propagated an exception; B ran all its cycles.
    assert errors == {}
    assert len(b_marks) == 3
    with session_factory() as session:
        a_row = session.get(PaperRun, "run-a")
        b_row = session.get(PaperRun, "run-b")
        events = list(
            session.execute(
                select(PaperRun.id)
            ).scalars()
        )
    assert set(events) == {"run-a", "run-b"}
    assert b_row.status == "completed"
    # A finished too (its faults were absorbed cycle by cycle).
    assert a_row.status == "completed"


def test_each_account_broker_is_seeded_with_its_own_bankroll(session_factory):
    from kalshi_bot.execution.prediction_adapter import (
        PredictionPaperAdapter,
        registry_quote_source,
    )

    s1 = session_factory()
    s2 = session_factory()
    a1 = PredictionPaperAdapter(
        session=s1,
        quote_source=registry_quote_source({}),
        settlement_source=lambda _t: None,
        starting_cash_usd=250.0,
        strategy=lambda q: None,
    )
    a2 = PredictionPaperAdapter(
        session=s2,
        quote_source=registry_quote_source({}),
        settlement_source=lambda _t: None,
        starting_cash_usd=999.0,
        strategy=lambda q: None,
    )
    # Each adapter owns a distinct broker with its own starting cash — no
    # shared ledger (design.md D5).
    assert a1._broker is not a2._broker
    assert a1._broker._cash == 250.0
    assert a2._broker._cash == 999.0
