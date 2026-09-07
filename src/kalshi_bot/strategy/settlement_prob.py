"""Settlement-aware KXBTC15M strategy (kxbtc15m-validation-rebuild §4.2/§4.3,
design decision "Prioritize settlement-aware probability").

The pipeline for one evaluation:

  1. Build `SettlementWindowFeatures` from the context's BRTI readings
     (§4.1). If the baseline `settlement_probability` cannot be computed
     (no reference average, no vol estimate), HOLD.
  2. Pass the raw baseline probability through a **calibrator** — by default
     the identity, but the walk-forward harness (§3.3) fits an isotonic
     calibrator on PRIOR folds only and injects it, so the test-fold
     probability is calibrated without any peeking. The calibrator's
     version/metadata rides on the `Decision` for the audit trail (§4.2).
  3. Turn the calibrated P(YES) into a side-consistent fair value and
     compare it to the SIDE-SPECIFIC executable price plus FULL expected
     friction (entry + modelled exit fee). Emit BUY_YES / BUY_NO only when
     the post-friction edge clears `min_edge`; otherwise HOLD (§4.3).

Kelly is not used here and no sizing happens here — the strategy only emits
a probability + direction + entry band + invalidation, exactly as
design.md's "Separate prediction from execution and sizing" requires. The
execution/risk layer sizes from the stop distance.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from kalshi_bot.signals.fees import (
    DEFAULT_FEE_CONFIG,
    FeeConfig,
    entry_fee_rate_at_price,
)
from kalshi_bot.signals.settlement_window import (
    DEFAULT_WINDOW_SECONDS,
    build_features,
    settlement_probability,
)
from kalshi_bot.strategy.base import Action, Decision, StrategyContext

# --- calibration ----------------------------------------------------------


class Calibrator(Protocol):
    """Maps a raw model probability in [0, 1] to a calibrated one. Fitted on
    prior-fold `(raw_p, realized_outcome)` pairs by the walk-forward harness;
    the strategy just applies it. `version` is recorded with each Decision."""

    @property
    def version(self) -> str: ...

    def calibrate(self, raw_p: float) -> float: ...


@dataclass(frozen=True)
class IdentityCalibrator:
    """No-op — the default when no calibration has been fitted (e.g. a plain
    single-window backtest, or the first walk-forward fold)."""

    version: str = "identity"

    def calibrate(self, raw_p: float) -> float:
        return min(1.0, max(0.0, raw_p))


@dataclass(frozen=True)
class IsotonicCalibrator:
    """Piecewise-constant monotone calibration fitted by the pool-adjacent-
    violators algorithm on `(raw_p, outcome)` pairs. Monotone by
    construction, so it can never re-order the model's ranking — it only
    corrects the *level*. Interpolated linearly between fitted knots and
    clamped to the fitted range's endpoints outside it.

    Build with `IsotonicCalibrator.fit(pairs, version=...)`. `version`
    should encode the fold / data range it was fitted on so the audit trail
    can tie a calibrated probability back to its calibration set (§4.2)."""

    knots_x: tuple[float, ...]
    knots_y: tuple[float, ...]
    version: str
    n_fit: int

    @staticmethod
    def fit(
        pairs: Sequence[tuple[float, float]],
        *,
        version: str,
    ) -> IsotonicCalibrator | IdentityCalibrator:
        """`pairs` = (raw_probability, realized_outcome in {0.0, 1.0}). Needs
        a handful of points to mean anything — returns an `IdentityCalibrator`
        (so callers get a valid `Calibrator` either way) when given fewer
        than 10."""
        clean = [(float(p), float(o)) for p, o in pairs]
        if len(clean) < 10:
            return IdentityCalibrator(version=f"{version}:insufficient_data_n{len(clean)}")

        # Group by x FIRST (sort by x only — never tie-break on the outcome,
        # which would sort a same-x block into 0s-then-1s and hand PAV an
        # already-monotone sequence). Each distinct raw probability becomes
        # one weighted point at its mean outcome.
        clean.sort(key=lambda t: t[0])
        xs: list[float] = []
        values: list[float] = []
        weights: list[float] = []
        for x, o in clean:
            if xs and abs(x - xs[-1]) <= 1e-9:
                w = weights[-1] + 1.0
                values[-1] = (values[-1] * weights[-1] + o) / w
                weights[-1] = w
            else:
                xs.append(x)
                values.append(o)
                weights.append(1.0)

        # Pool Adjacent Violators for isotonic (non-decreasing) regression.
        i = 0
        while i < len(values) - 1:
            if values[i] <= values[i + 1] + 1e-12:
                i += 1
                continue
            w = weights[i] + weights[i + 1]
            v = (values[i] * weights[i] + values[i + 1] * weights[i + 1]) / w
            values[i] = v
            weights[i] = w
            del values[i + 1]
            del weights[i + 1]
            del xs[i + 1]
            if i > 0:
                i -= 1
        return IsotonicCalibrator(
            knots_x=tuple(xs),
            knots_y=tuple(min(1.0, max(0.0, v)) for v in values),
            version=version,
            n_fit=len(clean),
        )

    def calibrate(self, raw_p: float) -> float:
        x = min(1.0, max(0.0, raw_p))
        xs, ys = self.knots_x, self.knots_y
        if x <= xs[0]:
            return ys[0]
        if x >= xs[-1]:
            return ys[-1]
        # linear interp between the bracketing knots
        lo = 0
        hi = len(xs) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if xs[mid] <= x:
                lo = mid
            else:
                hi = mid
        span = xs[hi] - xs[lo]
        if span <= 0:
            return ys[lo]
        frac = (x - xs[lo]) / span
        return ys[lo] + frac * (ys[hi] - ys[lo])


# --- strategy ---------------------------------------------------------------


@dataclass(frozen=True)
class SettlementProbConfig:
    min_edge: float = 0.03
    """Minimum post-friction expected edge per contract (dollars) to enter."""
    min_seconds_remaining: int = 60
    """Below this the outcome is nearly settled and the spread dominates —
    don't open."""
    max_seconds_remaining: int = 840
    """Above this (i.e. right at the open) there is essentially no
    information yet; wait for the window to develop."""
    drift_per_sec: float = 0.0
    """Assumed BRTI drift fed to the baseline model — 0.0 is the zero-drift
    null; §4.4's trend work may supply a non-zero estimate as a feature."""
    window_seconds: int = DEFAULT_WINDOW_SECONDS
    entry_band_cents: int = 4
    """Half-width of the entry price band placed around the decision price,
    so a fill materially worse than intended is rejected by the engine."""
    fee_config: FeeConfig = field(default_factory=lambda: DEFAULT_FEE_CONFIG)


@dataclass(frozen=True)
class SettlementProbInputs:
    """The model inputs recorded on the Decision for the §4.2 audit trail."""

    raw_probability: float
    calibrated_probability: float
    calibrator_version: str
    reference_avg: float | None
    drift_so_far: float | None
    seconds_remaining: int
    realized_vol_per_sec: float | None


class SettlementProbStrategy:
    name = "settlement_prob"

    def __init__(
        self,
        config: SettlementProbConfig | None = None,
        *,
        calibrator: Calibrator | None = None,
    ) -> None:
        self.config = config or SettlementProbConfig()
        self.calibrator: Calibrator = calibrator or IdentityCalibrator()

    def evaluate(self, context: StrategyContext) -> Decision:
        cfg = self.config

        def hold(reason: str) -> Decision:
            return Decision(
                action=Action.HOLD,
                market_ticker=context.market_ticker,
                strategy_name=self.name,
                hold_reason=reason,
            )

        if not context.brti_readings:
            return hold("no_brti_readings")

        features = build_features(
            context.brti_readings,
            now_ts=context.now_ts,
            open_ts=_infer_open_ts(context),
            close_ts=context.close_ts,
            window_seconds=cfg.window_seconds,
        )
        if not cfg.min_seconds_remaining <= features.seconds_remaining <= cfg.max_seconds_remaining:
            return hold("outside_time_window")

        raw_p = settlement_probability(
            features, vol_per_sec=None, drift_per_sec=cfg.drift_per_sec
        )
        if raw_p is None:
            return hold("baseline_probability_unavailable")

        cal_p = self.calibrator.calibrate(raw_p)
        inputs = SettlementProbInputs(
            raw_probability=raw_p,
            calibrated_probability=cal_p,
            calibrator_version=self.calibrator.version,
            reference_avg=features.reference_avg,
            drift_so_far=features.drift_so_far,
            seconds_remaining=features.seconds_remaining,
            realized_vol_per_sec=features.realized_vol_per_sec,
        )

        # Side-specific executable prices in cents. YES is bought at the ask;
        # NO is bought at (100 - yes_bid). A missing quote on a side means we
        # cannot trade that side.
        yes_ask = context.yes_ask_cents
        yes_bid = context.yes_bid_cents

        # Take the better of the two sides if it clears the threshold.
        best_action: Action | None = None
        best_price: int | None = None
        best_edge = cfg.min_edge
        if yes_ask is not None:
            yes_edge = _edge_dollars(cal_p, yes_ask, cfg)
            if yes_edge > best_edge:
                best_action, best_price, best_edge = Action.BUY_YES, yes_ask, yes_edge
        if yes_bid is not None:
            no_price = 100 - yes_bid
            no_edge = _edge_dollars(1.0 - cal_p, no_price, cfg)
            if no_edge > best_edge:
                best_action, best_price, best_edge = Action.BUY_NO, no_price, no_edge

        if best_action is None or best_price is None:
            return hold("edge_below_threshold")

        side_p = cal_p if best_action == Action.BUY_YES else 1.0 - cal_p
        return Decision(
            action=best_action,
            market_ticker=context.market_ticker,
            strategy_name=self.name,
            fair_probability=side_p,
            confidence=abs(cal_p - 0.5) * 2.0,
            fee_adjusted_edge=best_edge,
            entry_price_cents=best_price,
            min_entry_price_cents=max(1, best_price - cfg.entry_band_cents),
            max_entry_price_cents=min(99, best_price + cfg.entry_band_cents),
            model_meta=_meta_dict(inputs),
        )


def _meta_dict(inputs: SettlementProbInputs) -> dict[str, object]:
    """Flatten `SettlementProbInputs` to JSON primitives for
    `Decision.model_meta` / the persisted audit trail (§4.2)."""
    return {
        "model": "settlement_prob_baseline",
        "raw_probability": inputs.raw_probability,
        "calibrated_probability": inputs.calibrated_probability,
        "calibrator_version": inputs.calibrator_version,
        "reference_avg": inputs.reference_avg,
        "drift_so_far": inputs.drift_so_far,
        "seconds_remaining": inputs.seconds_remaining,
        "realized_vol_per_sec": inputs.realized_vol_per_sec,
    }


def _infer_open_ts(context: StrategyContext) -> int:
    """KXBTC15M windows are a fixed 15 minutes; if the caller did not stamp
    an explicit open on the context, derive it from the close."""
    explicit = context.extras.get("window_open_ts") if context.extras else None
    if isinstance(explicit, int | float):
        return int(explicit)
    return context.close_ts - 15 * 60


def _edge_dollars(p_side_wins: float, price_cents: int, cfg: SettlementProbConfig) -> float:
    """Expected value per contract for buying this side at `price_cents`,
    net of the entry fee AND a modelled exit fee (the position is
    marked-to-settlement here, but §4.3 wants FULL expected friction, and a
    real exit — stop or take-profit — pays a second taker fee). Both fees
    use the versioned `FeeConfig` taker coefficient.

        EV = p*(1 - c) - (1 - p)*c - entry_fee_rate(c) - exit_fee_rate(c)
    """
    c = price_cents / 100.0
    coef = cfg.fee_config.taker_coefficient
    entry_fee = entry_fee_rate_at_price(c, coefficient=coef)
    exit_fee = entry_fee_rate_at_price(c, coefficient=coef)
    return p_side_wins * (1.0 - c) - (1.0 - p_side_wins) * c - entry_fee - exit_fee


__all__ = [
    "Calibrator",
    "IdentityCalibrator",
    "IsotonicCalibrator",
    "SettlementProbConfig",
    "SettlementProbInputs",
    "SettlementProbStrategy",
]
