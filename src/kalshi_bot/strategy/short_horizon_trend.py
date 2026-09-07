"""Trend-conditioned settlement-aware strategy (kxbtc15m-validation-rebuild
§4.4).

This is the settlement-aware strategy (`strategy/settlement_prob`) with one
change: instead of feeding the baseline probability model a fixed
`drift_per_sec` of 0, it estimates the drift from the short-horizon BRTI
trend (`signals/short_horizon_trend`) and, optionally, refuses to trade
AGAINST a strong established trend or INTO an exhausted one.

design.md's rule for trend: it "must improve out-of-sample net value after
execution costs" over the plain settlement baseline. This module exists so
§4.6's walk-forward report can run both — plain baseline and
trend-conditioned — through the same harness and compare. It is NOT
presumed to be an edge.

Everything is causal (features from BRTI readings <= now_ts) and no sizing
happens here — same contract as `SettlementProbStrategy`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from kalshi_bot.signals.short_horizon_trend import (
    DEFAULT_PULLBACK_LOOKBACK_SECONDS,
    DEFAULT_TREND_LOOKBACK_SECONDS,
    build_trend_features,
)
from kalshi_bot.strategy.base import Action, Decision, StrategyContext
from kalshi_bot.strategy.settlement_prob import (
    Calibrator,
    SettlementProbConfig,
    SettlementProbStrategy,
)


@dataclass(frozen=True)
class TrendConditionedConfig:
    base: SettlementProbConfig = field(default_factory=SettlementProbConfig)

    trend_lookback_seconds: int = DEFAULT_TREND_LOOKBACK_SECONDS
    pullback_lookback_seconds: int = DEFAULT_PULLBACK_LOOKBACK_SECONDS

    use_trend_drift: bool = True
    """Feed the OLS slope of BRTI as `drift_per_sec` to the baseline model
    instead of 0. This is the whole point of the variant; turning it off
    makes this strategy identical to the plain baseline (useful as a
    control in the §4.6 comparison)."""

    drift_scale: float = 1.0
    """Multiplier on the raw slope before it is used as drift — a
    conservative default of <=1 keeps a noisy slope from dominating the
    probability. A walk-forward parameter."""

    max_adverse_trend_z: float | None = None
    """If set, HOLD when the trade direction would be AGAINST an established
    short-horizon trend of at least this |trend_z| (fading a strong move is
    exactly the failure mode v2's trend strategies hit). None disables."""

    min_pullback_fraction: float | None = None
    """If set, HOLD when following the trend but the pullback has already
    retraced less than this fraction (i.e. entering with no pullback at
    all — chasing). None disables."""


@dataclass(frozen=True)
class TrendMeta:
    slope_per_sec: float | None
    trend_z: float | None
    pullback_fraction: float | None
    pullback_direction: int
    drift_per_sec_used: float


class TrendConditionedSettlementStrategy:
    name = "settlement_trend"

    def __init__(
        self,
        config: TrendConditionedConfig | None = None,
        *,
        calibrator: Calibrator | None = None,
    ) -> None:
        self.config = config or TrendConditionedConfig()
        self._calibrator = calibrator

    def evaluate(self, context: StrategyContext) -> Decision:
        cfg = self.config

        def hold(reason: str) -> Decision:
            return Decision(
                action=Action.HOLD,
                market_ticker=context.market_ticker,
                strategy_name=self.name,
                hold_reason=reason,
            )

        tf = build_trend_features(
            context.brti_readings,
            now_ts=context.now_ts,
            trend_lookback_seconds=cfg.trend_lookback_seconds,
            pullback_lookback_seconds=cfg.pullback_lookback_seconds,
        )

        drift = 0.0
        if cfg.use_trend_drift and tf.slope_per_sec is not None:
            drift = tf.slope_per_sec * cfg.drift_scale

        base_cfg = replace(cfg.base, drift_per_sec=drift)
        base = SettlementProbStrategy(base_cfg, calibrator=self._calibrator)
        decision = base.evaluate(context)

        if decision.action == Action.HOLD:
            return decision  # base already declined; nothing to add

        # Trend gates, applied to the base's chosen direction.
        going_up = decision.action == Action.BUY_YES
        if (
            cfg.max_adverse_trend_z is not None
            and tf.trend_z is not None
            and abs(tf.trend_z) >= cfg.max_adverse_trend_z
        ):
            trend_up = tf.trend_z > 0
            if trend_up != going_up:
                return hold("against_established_trend")
        if (
            cfg.min_pullback_fraction is not None
            and tf.pullback_fraction is not None
            and tf.pullback_direction != 0
        ):
            following_trend = (tf.pullback_direction > 0) == going_up
            if following_trend and tf.pullback_fraction < cfg.min_pullback_fraction:
                return hold("no_pullback_chasing")

        meta = dict(decision.model_meta)
        meta["trend"] = _trend_meta_dict(
            TrendMeta(
                slope_per_sec=tf.slope_per_sec,
                trend_z=tf.trend_z,
                pullback_fraction=tf.pullback_fraction,
                pullback_direction=tf.pullback_direction,
                drift_per_sec_used=drift,
            )
        )
        meta["model"] = "settlement_prob_trend_conditioned"
        return replace(decision, strategy_name=self.name, model_meta=meta)


def _trend_meta_dict(m: TrendMeta) -> dict[str, object]:
    return {
        "slope_per_sec": m.slope_per_sec,
        "trend_z": m.trend_z,
        "pullback_fraction": m.pullback_fraction,
        "pullback_direction": m.pullback_direction,
        "drift_per_sec_used": m.drift_per_sec_used,
    }


__all__ = [
    "TrendConditionedConfig",
    "TrendConditionedSettlementStrategy",
    "TrendMeta",
]
