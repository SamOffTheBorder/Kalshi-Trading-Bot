"""Unit tests must be hermetic: scrub host env vars that Settings would read.

(Discovered the hard way: this dev machine has a real OPENROUTER_API_KEY set,
which leaked into 'default construction' tests.)
"""

import pytest

# Dashboard read-model state fixtures (trader-dashboard-experience task 1.4):
# fresh/stale/empty/partial/error, duplicate paper capital, partial fills and
# disconnected runners.
#
# Re-exported here rather than declared via `pytest_plugins`, which pytest
# forbids outside a top-level conftest. Importing the names into this conftest
# registers them for every test under `tests/unit/` just the same, without
# adding a root-level conftest solely for this change.
from tests.unit.conftest_dashboard_states import (  # noqa: F401
    dashboard_session,
    disconnected_runner_state,
    duplicate_paper_capital,
    empty_state,
    error_state,
    fresh_state,
    partial_fill_state,
    partial_state,
    stale_state,
)

from kalshi_bot.config.settings import Settings


@pytest.fixture(autouse=True)
def _isolate_settings_env(monkeypatch):
    for field_name in Settings.model_fields:
        monkeypatch.delenv(field_name.upper(), raising=False)
