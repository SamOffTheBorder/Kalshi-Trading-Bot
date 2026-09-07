"""Single source of truth for all configuration.

Every configurable value in the bot lives here and nowhere else. The committed
`.env.example` is GENERATED from this model by `scripts/generate_env_example.py`
(enforced by a test + CI), so the example file cannot drift from reality — the
exact failure mode that shipped in the previous version of this project.

Secrets use `SecretStr` so they are never printed in logs/reprs and are emitted
as blank lines in the generated `.env.example`. All credentials default to None:
backtesting against public historical data must work with zero credentials.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from kalshi_bot.config.crypto_registry import (
    DEFAULT_CRYPTO_REGISTRY,
    CryptoAssetConfig,
    validate_registry,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    # --- Mode ---------------------------------------------------------------
    paper_trading: bool = Field(
        default=True,
        description="Master switch. True = simulated fills only. Flipping to False is "
        "gated behind the live-trading confirmation flow; never edit casually.",
    )

    # --- Kalshi -------------------------------------------------------------
    kalshi_key_id: SecretStr | None = Field(
        default=None,
        description="Kalshi API key ID from the Kalshi dashboard. Not needed for backtesting.",
    )
    kalshi_private_key_path: Path = Field(
        default=Path("secrets/kalshi_private_key.pem"),
        description="Path to the RSA private key PEM used for RSA-PSS request signing. "
        "Keep under secrets/ (gitignored). Kalshi cannot recover a lost key; rotate ~90 days.",
    )
    kalshi_use_demo_env: bool = Field(
        default=True,
        description="True = Kalshi demo environment; False = production exchange.",
    )
    live_trading_confirmation_phrase: SecretStr | None = Field(
        default=None,
        description="Required before any Kalshi client will place/amend a real order or "
        "exit trigger against production with paper_trading=False. Must be set to the "
        "literal phrase 'I understand this places real orders' (case-sensitive) for the "
        "guard to open; anything else, including unset, keeps production order placement "
        "blocked. This is the live-trading confirmation flow referenced by paper_trading's "
        "own description above — a deliberate typing exercise, not a UI, so flipping to "
        "live trading can never happen by editing one boolean.",
    )

    # --- Bankroll & sizing ----------------------------------------------------
    bankroll_total_usd: float = Field(
        default=200.0,
        gt=0,
        description="Total trading capital, in USD.",
    )
    kelly_fraction: float = Field(
        default=0.25,
        gt=0.0,
        le=0.5,
        description="Fractional Kelly multiplier. 0.25 = quarter-Kelly (conservative default; "
        "edge estimates are uncertain). Documented tunable band: 0.25-0.5. Backtest "
        "comparison only (design D3) — does not size live orders.",
    )
    risk_pct: float = Field(
        default=0.01,
        gt=0.0,
        le=0.02,
        description="Fixed-fractional risk per trade for live sizing (risk/fixed_risk.py, "
        "design D3): fraction of equity lost if the stop is hit. Documented tunable band: "
        "1-2%. Replaces Kelly on the live path — Kelly requires a win-probability estimate "
        "Phase 1 proved untrustworthy (model said 40%, actually won 20%).",
    )
    max_leverage: float = Field(
        default=2.0,
        gt=0.0,
        le=3.0,
        description="Perps leverage cap (risk/leverage_governor.py, spec: perps-trading "
        "'Leverage ceiling below exchange maximum'). Default 2x; hard ceiling 3x regardless "
        "of the higher maximum Kalshi itself permits — enforced in code "
        "(HARD_LEVERAGE_CEILING), not just by this field's bound.",
    )
    max_position_pct: float = Field(
        default=0.05,
        gt=0.0,
        le=0.10,
        description="Hard cap on any single position as a fraction of that broker's bankroll, "
        "applied AFTER Kelly sizing as a min() clamp. Kelly output can never exceed this.",
    )

    # --- Strategy gates ---------------------------------------------------------
    min_edge: float = Field(
        default=0.05,
        gt=0.0,
        lt=0.5,
        description="Minimum fee-adjusted edge (expected value per contract dollar) "
        "required to enter. Fee is subtracted BEFORE this gate.",
    )
    max_model_divergence: float = Field(
        default=0.06,
        gt=0.0,
        lt=0.5,
        description="Maximum |BS - MC| probability disagreement. Larger divergence "
        "means the pricing model is strained -> HOLD regardless of apparent edge.",
    )
    min_entry_probability: float = Field(
        default=0.30,
        ge=0.0,
        le=1.0,
        description="Skip contracts whose estimated win probability is below this "
        "(longshot-bias guard; v1's losses clustered in cheap contracts).",
    )
    max_entry_probability: float = Field(
        default=0.80,
        ge=0.0,
        le=1.0,
        description="Skip contracts whose estimated win probability is above this "
        "(overpriced-favorite guard; thin payoff rarely survives fees).",
    )
    min_minutes_to_expiry: float = Field(
        default=10.0,
        ge=0.0,
        description="No new entries closer to expiry than this — near-expiry gamma "
        "noise makes model estimates unreliable.",
    )
    max_trend_zscore: float = Field(
        default=1.5,
        gt=0.0,
        description="Trend-regime gate: HOLD when |realized log-return over the lookback| "
        "exceeds this many model sigmas (vol*sqrt(t)). The zero-drift BS/MC pricer fades "
        "trends it cannot see — run #4's losses all came from one such episode.",
    )
    trend_lookback_hours: float = Field(
        default=24.0,
        gt=0.0,
        description="Lookback window (hours) for the trend-regime z-score.",
    )
    max_entries_per_series_window: int = Field(
        default=3,
        ge=1,
        description="Episode/cluster guard: max filled entries per series within the "
        "rolling entry_throttle_window_hours. Backtest run #4 lost to 23 entries "
        "fading one 15-hour trend; per-trade caps alone don't bound an episode.",
    )
    entry_throttle_window_hours: float = Field(
        default=24.0,
        gt=0.0,
        description="Rolling window (hours) over which max_entries_per_series_window is enforced.",
    )

    # --- Drawdown circuit breakers -------------------------------------------
    max_drawdown_pause_pct: float = Field(
        default=0.25,
        gt=0.0,
        lt=1.0,
        description="Drawdown from peak (per broker) at which NEW entries pause. "
        "Recalibrate against backtest output before live trading.",
    )
    max_drawdown_halt_pct: float = Field(
        default=0.40,
        gt=0.0,
        lt=1.0,
        description="Drawdown from peak (per broker) triggering full halt + close-all "
        "via EmergencyControl. Must be > max_drawdown_pause_pct.",
    )
    drawdown_peak_window_days: float = Field(
        default=7.0,
        gt=0.0,
        description="Trailing window (days) for the drawdown guard's reference peak. "
        "An all-time peak makes PAUSE permanently sticky in a settle-to-flat book "
        "(equity can't move while paused) — backtest runs #3-#5 starved every "
        "out-of-sample segment this way. HALT stays sticky regardless.",
    )
    max_daily_loss_usd: float = Field(
        default=20.0,
        gt=0.0,
        description="Halt new entries for the rest of the UTC day once realized PnL since "
        "midnight UTC falls below -max_daily_loss_usd (risk/daily_loss_guard.py, "
        "EmergencyControl). Independent of the broader equity-curve DrawdownGuard — a bad "
        "day can trip this without yet being a broader drawdown.",
    )
    max_consecutive_losses: int = Field(
        default=5,
        ge=1,
        description="Halt new entries after this many losing trades in a row (any win "
        "resets the streak). A losing streak usually means the strategy's edge assumption "
        "broke for current conditions, a distinct failure mode from ordinary variance "
        "(risk/daily_loss_guard.py, EmergencyControl).",
    )

    # --- AI layer -------------------------------------------------------------
    openrouter_api_key: SecretStr | None = Field(
        default=None,
        description="OpenRouter API key. Used ONLY for sparse high-stakes calls "
        "(pre-trade veto, periodic strategy review).",
    )
    openrouter_monthly_budget_usd: float = Field(
        default=15.0,
        ge=0.0,
        description="Hard monthly cap on OpenRouter spend. On exhaustion the bot falls back "
        "to :free-tier models / local Ollama; the veto gate stays fail-closed.",
    )
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Local Ollama endpoint for routine/frequent LLM tasks (regime classification).",
    )

    # --- Notifications ---------------------------------------------------------
    telegram_bot_token: SecretStr | None = Field(
        default=None,
        description="Telegram bot token from @BotFather. Optional; enables Telegram "
        "alerts + commands.",
    )
    telegram_chat_id: str | None = Field(
        default=None,
        description="Telegram chat ID authorized to command the bot. Commands from "
        "other chats are ignored.",
    )
    discord_bot_token: SecretStr | None = Field(
        default=None,
        description="Discord bot token. Optional; enables Discord alerts + commands.",
    )

    # --- Storage & ops ----------------------------------------------------------
    db_path: Path = Field(
        default=Path("data/kalshi_bot.db"),
        description="SQLite database path (single schema of record). Portable to Postgres later.",
    )
    log_level: str = Field(
        default="INFO",
        description="Log level: DEBUG, INFO, WARNING, ERROR.",
    )
    dashboard_auth_secret: SecretStr | None = Field(
        default=None,
        description="Shared secret for the LAN-exposed dashboard. Required before "
        "the web UI starts.",
    )

    crypto_registry: tuple[CryptoAssetConfig, ...] = Field(
        default=DEFAULT_CRYPTO_REGISTRY,
        description=(
            "JSON registry of crypto assets; lifecycle and venue mappings are validated before use."
        ),
    )

    @field_validator("crypto_registry")
    @classmethod
    def _validate_crypto_registry(
        cls, value: tuple[CryptoAssetConfig, ...]
    ) -> tuple[CryptoAssetConfig, ...]:
        return validate_registry(value)

    @field_validator("max_drawdown_halt_pct")
    @classmethod
    def _halt_above_pause(cls, v: float, info) -> float:
        pause = info.data.get("max_drawdown_pause_pct")
        if pause is not None and v <= pause:
            raise ValueError(
                f"max_drawdown_halt_pct ({v}) must be greater than max_drawdown_pause_pct ({pause})"
            )
        return v


@lru_cache
def get_settings() -> Settings:
    """Process-wide cached settings instance."""
    return Settings()
