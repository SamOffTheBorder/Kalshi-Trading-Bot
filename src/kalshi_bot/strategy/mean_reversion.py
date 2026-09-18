"""Settlement-aware, bounded mean-reversion candidate for KXBTC15M.

This candidate is not a generic RSI/reversal strategy.  It uses only BRTI
readings usable at decision time, converts a statistically unusual BRTI
displacement into a bounded expected drift back toward its trailing mean, and
then delegates probability and executable-price economics to the established
settlement-aware strategy.  A strong directional trend blocks entry so the
candidate cannot silently become an unfiltered attempt to fade momentum.

It is research-only.  ``validation_run`` compares it with the settlement
baseline fold by fold and fails its promotion verdict unless the incremental
fully-costed net result is positive in every fold.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from kalshi_bot.signals.mean_reversion import (
    DEFAULT_MEAN_REVERSION_LOOKBACK_SECONDS,
    DEFAULT_MEAN_REVERSION_MIN_SAMPLES,
    MeanReversionFeatures,
    build_mean_reversion_features,
)
from kalshi_bot.signals.short_horizon_trend import build_trend_features
from kalshi_bot.strategy.base import Action, Decision, StrategyContext
from kalshi_bot.strategy.settlement_prob import (
    Calibrator,
    SettlementProbConfig,
    SettlementProbStrategy,
)


@dataclass(frozen=True)
class MeanReversionConfig:
    base: SettlementProbConfig = field(default_factory=SettlementProbConfig)
    lookback_seconds: int = DEFAULT_MEAN_REVERSION_LOOKBACK_SECONDS
    min_samples: int = DEFAULT_MEAN_REVERSION_MIN_SAMPLES
    min_abs_zscore: float = 2.0
    max_trend_zscore: float = 1.5
    reversion_horizon_seconds: int = 120
    reversion_strength: float = 0.5


class MeanReversionSettlementStrategy:
    """Apply a bounded, causal reversion drift to settlement probability."""

    name = "settlement_mean_reversion"

    def __init__(
        self,
        config: MeanReversionConfig | None = None,
        *,
        calibrator: Calibrator | None = None,
    ) -> None:
        self.config = config or MeanReversionConfig()
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

        if cfg.min_abs_zscore <= 0:
            raise ValueError("min_abs_zscore must be positive")
        if cfg.max_trend_zscore <= 0:
            raise ValueError("max_trend_zscore must be positive")
        if cfg.reversion_horizon_seconds <= 0:
            raise ValueError("reversion_horizon_seconds must be positive")
        if not 0 < cfg.reversion_strength <= 1:
            raise ValueError("reversion_strength must be in (0, 1]")

        features = build_mean_reversion_features(
            context.brti_readings,
            now_ts=context.now_ts,
            lookback_seconds=cfg.lookback_seconds,
            min_samples=cfg.min_samples,
        )
        if features.zscore is None or features.displacement is None:
            return hold("mean_reversion_features_unavailable")
        if abs(features.zscore) < cfg.min_abs_zscore:
            return hold("mean_reversion_signal_too_weak")

        trend = build_trend_features(
            context.brti_readings,
            now_ts=context.now_ts,
            trend_lookback_seconds=cfg.lookback_seconds,
            pullback_lookback_seconds=cfg.lookback_seconds,
        )
        if trend.trend_z is not None and abs(trend.trend_z) > cfg.max_trend_zscore:
            return hold("mean_reversion_trend_regime")

        horizon = min(cfg.reversion_horizon_seconds, int(context.minutes_to_expiry * 60))
        if horizon <= 0:
            return hold("outside_time_window")
        reversion_drift = -cfg.reversion_strength * features.displacement / horizon
        base = SettlementProbStrategy(
            replace(cfg.base, drift_per_sec=reversion_drift), calibrator=self._calibrator
        )
        decision = base.evaluate(context)
        if decision.action == Action.HOLD:
            return replace(decision, strategy_name=self.name)

        metadata = dict(decision.model_meta)
        metadata["model"] = "settlement_prob_mean_reversion"
        metadata["mean_reversion"] = _meta_dict(
            features,
            reversion_drift=reversion_drift,
            trend_z=trend.trend_z,
        )
        return replace(decision, strategy_name=self.name, model_meta=metadata)


def _meta_dict(
    features: MeanReversionFeatures,
    *,
    reversion_drift: float,
    trend_z: float | None,
) -> dict[str, float | int | None]:
    return {
        "last_value": features.last_value,
        "trailing_mean": features.trailing_mean,
        "trailing_std": features.trailing_std,
        "displacement": features.displacement,
        "zscore": features.zscore,
        "sample_count": features.sample_count,
        "reversion_drift_per_sec": reversion_drift,
        "trend_z": trend_z,
    }


__all__ = ["MeanReversionConfig", "MeanReversionSettlementStrategy"]
