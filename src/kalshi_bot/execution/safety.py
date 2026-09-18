"""Execution-safety invariants shared by paper and live callers."""

from __future__ import annotations


def require_linear_hedge_instrument(instrument: str, *, is_binary: bool = False) -> None:
    """Reject event contracts when a caller asks for a linear hedge."""
    if is_binary or instrument.upper().startswith(("KX", "INX", "NASDAQ")):
        raise ValueError(f"binary contract {instrument!r} cannot be used as a linear hedge")


__all__ = ["require_linear_hedge_instrument"]
