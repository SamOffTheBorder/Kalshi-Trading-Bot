from kalshi_bot.data.reconstruction_error import (
    MEASURED,
    UNMEASURED,
    IndexPoint,
    level_error,
    measure_reconstruction_error,
    resolution_agreement,
)


def _series(values: dict[int, float]) -> tuple[IndexPoint, ...]:
    return tuple(IndexPoint(observed_at=t, value=v) for t, v in sorted(values.items()))


def test_level_error_computes_mean_and_max_over_overlap_only():
    captured = _series({0: 100.0, 1: 101.0, 2: 100.0})
    reconstructed = _series({1: 102.0, 2: 99.0, 3: 50.0})  # t=3 has no captured counterpart
    result = level_error(captured, reconstructed)
    assert result is not None
    mean_abs, max_abs = result
    assert mean_abs == 1.0
    assert max_abs == 1.0


def test_level_error_is_none_when_no_overlap():
    captured = _series({0: 100.0})
    reconstructed = _series({10: 100.0})
    assert level_error(captured, reconstructed) is None


def test_report_is_unmeasured_when_no_captured_coverage_exists():
    reconstructed = _series({t: 100.0 for t in range(0, 200)})
    report = measure_reconstruction_error(
        captured=(), reconstructed=reconstructed, contract_windows=((60, 900),)
    )
    assert report.status == UNMEASURED
    assert report.resolution_agreement is None


def test_resolution_agreement_uses_the_contracts_own_settlement_rule():
    # A 900s window: reference average is the 60s ending at open_ts=60;
    # close average is the 60s ending at close_ts=900. Both series flat and
    # rising identically -> same YES outcome for both.
    captured = _series({t: 100.0 + (t / 900) for t in range(0, 901)})
    reconstructed = _series({t: 100.0 + (t / 900) for t in range(0, 901)})
    result = resolution_agreement(
        captured, reconstructed, contract_windows=((60, 900),), window_seconds=60
    )
    assert result is not None
    agreement, evaluated = result
    assert evaluated == 1
    assert agreement == 1.0


def test_report_is_unmeasured_when_windows_cannot_be_evaluated():
    # Overlap exists but is too short to cover any 60s window ending at the
    # open/close timestamps of the only requested contract.
    captured = _series({500: 100.0})
    reconstructed = _series({500: 100.0})
    report = measure_reconstruction_error(
        captured, reconstructed, contract_windows=((60, 900),)
    )
    assert report.status == UNMEASURED


def test_close_level_agreement_can_still_diverge_on_resolution_outcome():
    """The case that motivates resolution_agreement over price error alone
    (design D4): a reconstruction that tracks level within a hair can still
    flip the coin-flip settlement outcome, and the report must show that
    plainly rather than being flattered by a tiny mean_abs_diff."""

    open_ts, close_ts = 60, 900
    # Captured: reference window flat at 100; close window nudges to 100.02
    # (a hair's-width YES).
    captured_values = {t: 100.0 for t in range(0, 61)}
    captured_values.update({t: 100.02 for t in range(840, 901)})
    captured = _series(captured_values)

    # Reconstructed: near-identical level (off by ~0.01, tiny mean_abs_diff)
    # but its close window sits at 99.99 -- a NO instead of a YES.
    reconstructed_values = {t: 100.01 for t in range(0, 61)}
    reconstructed_values.update({t: 99.99 for t in range(840, 901)})
    reconstructed = _series(reconstructed_values)

    report = measure_reconstruction_error(
        captured, reconstructed, contract_windows=((open_ts, close_ts),), window_seconds=60
    )
    assert report.status == MEASURED
    # Level tracks closely...
    assert report.mean_abs_diff is not None
    assert report.mean_abs_diff < 0.05
    # ...but the settlement outcome disagreed on the one contract evaluated.
    assert report.contracts_evaluated == 1
    assert report.resolution_agreement == 0.0
