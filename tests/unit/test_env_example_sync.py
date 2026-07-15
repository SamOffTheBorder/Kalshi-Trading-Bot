"""Fail the build if `.env.example` drifts from the Settings model.

The old bot's `.env.example` documented an auth method the code didn't even use.
This test makes that class of bug a CI failure instead of a runtime surprise.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from generate_env_example import render_env_example  # noqa: E402


def test_env_example_matches_settings_model():
    committed = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    expected = render_env_example()
    assert committed == expected, (
        ".env.example is out of sync with src/kalshi_bot/config/settings.py.\n"
        "Regenerate it:  uv run python scripts/generate_env_example.py"
    )
