"""Unit tests must be hermetic: scrub host env vars that Settings would read.

(Discovered the hard way: this dev machine has a real OPENROUTER_API_KEY set,
which leaked into 'default construction' tests.)
"""

import pytest

from kalshi_bot.config.settings import Settings


@pytest.fixture(autouse=True)
def _isolate_settings_env(monkeypatch):
    for field_name in Settings.model_fields:
        monkeypatch.delenv(field_name.upper(), raising=False)
