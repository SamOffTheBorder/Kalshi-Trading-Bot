"""Generate `.env.example` from the Settings model — the single source of truth.

Never edit `.env.example` by hand. A pytest (tests/unit/test_env_example_sync.py)
fails if the committed file differs from what this script produces, so config
documentation cannot drift from the code that actually reads it.

Usage:  uv run python scripts/generate_env_example.py
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

from pydantic import SecretStr
from pydantic_core import PydanticUndefined

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from kalshi_bot.config.settings import Settings  # noqa: E402

HEADER = """\
# =============================================================================
# kalshi-bot configuration
#
# GENERATED FILE — do not edit by hand.
# Source of truth: src/kalshi_bot/config/settings.py
# Regenerate with:  uv run python scripts/generate_env_example.py
#
# Copy to `.env` and fill in values. Secrets are left blank; all credentials
# are optional — backtesting against public data needs none of them.
# =============================================================================
"""


def _default_repr(field) -> str:
    default = field.default
    if default is None or default is PydanticUndefined:
        return ""
    annotation = field.annotation
    if annotation is SecretStr or (
        hasattr(annotation, "__args__") and SecretStr in getattr(annotation, "__args__", ())
    ):
        return ""
    if isinstance(default, bool):
        return str(default).lower()
    return str(default)


def render_env_example() -> str:
    lines: list[str] = [HEADER]
    for name, field in Settings.model_fields.items():
        description = field.description or ""
        for wrapped in textwrap.wrap(description, width=96):
            lines.append(f"# {wrapped}")
        lines.append(f"{name.upper()}={_default_repr(field)}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    out = REPO_ROOT / ".env.example"
    out.write_text(render_env_example(), encoding="utf-8", newline="\n")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
