"""Safe report serialization that omits credentials and key material."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SENSITIVE_TOKENS = ("secret", "token", "password", "private_key", "key_id", "authorization")


def redact_export(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: (
                "[REDACTED]"
                if any(token in key.lower() for token in SENSITIVE_TOKENS)
                else redact_export(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_export(item) for item in value]
    if isinstance(value, tuple):
        return [redact_export(item) for item in value]
    return value


__all__ = ["redact_export"]
