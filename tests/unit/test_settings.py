"""Settings model invariants — the config bugs that shipped in the old bot."""

import pytest
from pydantic import ValidationError

from kalshi_bot.config.settings import Settings


def _bare_settings(**overrides) -> Settings:
    """Settings without reading any real .env file."""
    return Settings(_env_file=None, **overrides)


def test_defaults_construct_without_any_credentials():
    """Backtesting must work with zero credentials configured."""
    s = _bare_settings()
    assert s.paper_trading is True
    assert s.kalshi_key_id is None
    assert s.webull_app_key is None
    assert s.openrouter_api_key is None


def test_paper_trading_defaults_on():
    assert _bare_settings().paper_trading is True


def test_sandbox_and_demo_default_on():
    s = _bare_settings()
    assert s.kalshi_use_demo_env is True
    assert s.webull_use_sandbox is True


def test_halt_threshold_must_exceed_pause_threshold():
    """The old bot shipped a three-way disagreement on these values; now invalid
    combinations are unrepresentable."""
    with pytest.raises(ValidationError):
        _bare_settings(max_drawdown_pause_pct=0.40, max_drawdown_halt_pct=0.25)


def test_kelly_fraction_capped_at_half_kelly():
    with pytest.raises(ValidationError):
        _bare_settings(kelly_fraction=0.75)


def test_max_position_hard_cap_bounded():
    with pytest.raises(ValidationError):
        _bare_settings(max_position_pct=0.5)


def test_secrets_never_leak_in_repr():
    s = _bare_settings(kalshi_key_id="super-secret-key-id")
    assert "super-secret-key-id" not in repr(s)
    assert "super-secret-key-id" not in str(s)


def test_unknown_env_keys_rejected():
    """extra='forbid' — a typoed setting fails loudly instead of being ignored."""
    with pytest.raises(ValidationError):
        _bare_settings(some_typoed_setting=True)
