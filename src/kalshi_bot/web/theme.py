"""Operator color theme: stored server-side (`DashboardSetting`), rendered as
a `<style>` block in `_base.html` so there is no flash-of-default-theme and
no client-side JS dependency to change how the dashboard looks.

Persisted as a flat color dict rather than one settings row per color: the
whole palette is one coherent choice, and a partial/corrupt override should
fall back to defaults key-by-key rather than blanking the page.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from sqlalchemy import select
from sqlalchemy.orm import Session

from kalshi_bot.storage.models import DashboardSetting

THEME_SETTING_KEY = "theme_colors"


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def _dim(value: str, *, mix_with: str, weight: float = 0.18) -> str:
    """A low-saturation background tint for a badge/status color, blended
    toward the panel color rather than toward black — keeps dark and light
    palettes both legible without a separate "dim" picker per color."""
    r1, g1, b1 = _hex_to_rgb(value)
    r2, g2, b2 = _hex_to_rgb(mix_with)
    r = round(r1 * weight + r2 * (1 - weight))
    g = round(g1 * weight + g2 * (1 - weight))
    b = round(b1 * weight + b2 * (1 - weight))
    return f"#{r:02x}{g:02x}{b:02x}"


@dataclass(frozen=True)
class ThemeColors:
    """Every CSS custom property an operator can override. Field names match
    the `--foo` CSS variables in style.css with dashes turned to underscores."""

    bg: str = "#0d0f13"
    panel: str = "#151920"
    panel_2: str = "#1b2029"
    border: str = "#262c37"
    text: str = "#e8eaee"
    text_dim: str = "#a2a9b6"
    muted: str = "#79808d"
    green: str = "#3ecf8e"
    red: str = "#f0555a"
    amber: str = "#e8b339"
    blue: str = "#5a9cf8"

    def as_dict(self) -> dict[str, str]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def css_var_name(self, field_name: str) -> str:
        return f"--{field_name.replace('_', '-')}"


PRESETS: dict[str, ThemeColors] = {
    "default": ThemeColors(),
    "midnight-blue": ThemeColors(
        bg="#0a0e17", panel="#111827", panel_2="#161f33", border="#232f47",
        text="#e7ecf7", text_dim="#a3b0c9", muted="#71809e",
        green="#41d1a4", red="#ff6b73", amber="#f5c04d", blue="#6ea8fe",
    ),
    "high-contrast": ThemeColors(
        bg="#000000", panel="#0c0c0c", panel_2="#161616", border="#3a3a3a",
        text="#ffffff", text_dim="#c9c9c9", muted="#8f8f8f",
        green="#00e676", red="#ff3b3b", amber="#ffcc00", blue="#4dabff",
    ),
    "light": ThemeColors(
        bg="#f5f6f8", panel="#ffffff", panel_2="#eef0f4", border="#d8dce3",
        text="#12141a", text_dim="#454b57", muted="#6b7280",
        green="#0e9f6e", red="#d9363e", amber="#b7791f", blue="#2f6fed",
    ),
}

_HEX_RE_LEN = {4, 7}  # "#abc" or "#aabbcc"


def _is_valid_hex(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) in _HEX_RE_LEN
        and value.startswith("#")
        and all(c in "0123456789abcdefABCDEF" for c in value[1:])
    )


def load_theme(session: Session) -> ThemeColors:
    """Read the saved palette, filling any missing/invalid field from
    defaults so a partial override (or a future field added to
    ThemeColors) never breaks rendering."""
    row = session.execute(
        select(DashboardSetting).where(DashboardSetting.key == THEME_SETTING_KEY)
    ).scalar_one_or_none()
    if row is None or not isinstance(row.value, dict):
        return ThemeColors()
    defaults = ThemeColors().as_dict()
    merged = {
        name: (row.value.get(name) if _is_valid_hex(row.value.get(name)) else default)
        for name, default in defaults.items()
    }
    return ThemeColors(**merged)


def save_theme(session: Session, colors: ThemeColors) -> None:
    row = session.execute(
        select(DashboardSetting).where(DashboardSetting.key == THEME_SETTING_KEY)
    ).scalar_one_or_none()
    if row is None:
        row = DashboardSetting(key=THEME_SETTING_KEY, value=colors.as_dict())
        session.add(row)
    else:
        row.value = colors.as_dict()
    session.commit()


def theme_css(colors: ThemeColors) -> str:
    """A `:root { ... }` block overriding style.css's defaults, including
    the derived `-dim` badge-background variants. Injected inline in
    `<head>` so it applies before first paint (no client-side theme flash)."""
    lines = [f"  {colors.css_var_name(name)}: {value};" for name, value in colors.as_dict().items()]
    lines.append(f"  --border-soft: {_dim(colors.border, mix_with=colors.panel, weight=0.6)};")
    for status in ("green", "red", "amber", "blue"):
        value = getattr(colors, status)
        lines.append(f"  --{status}-dim: {_dim(value, mix_with=colors.panel)};")
    return ":root {\n" + "\n".join(lines) + "\n}"


__all__ = ["PRESETS", "ThemeColors", "load_theme", "save_theme", "theme_css"]
