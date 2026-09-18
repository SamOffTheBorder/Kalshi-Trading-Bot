"""Provider-neutral, bounded in-process agent invocation."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from typing import Protocol

from kalshi_bot.agents.contracts import AgentRole


@dataclass(frozen=True)
class AgentRequest:
    role: AgentRole
    agent_id: str
    payload: Mapping[str, object]
    timeout_seconds: float
    max_output_tokens: int
    max_cost_usd: float
    attempt: int = 1

    @property
    def request_hash(self) -> str:
        body = {
            "role": self.role,
            "agent_id": self.agent_id,
            "payload": self.payload,
            "max_output_tokens": self.max_output_tokens,
            "attempt": self.attempt,
        }
        return hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()


@dataclass(frozen=True)
class AgentCallResult:
    status: str
    raw_output: str | None
    request_hash: str
    latency_ms: int
    error: str | None = None


class AgentClient(Protocol):
    def invoke(self, request: AgentRequest) -> AgentCallResult: ...


class InProcessAgentClient:
    """Small adapter used by tests and the first local implementation.

    The handler is deliberately passed only a request payload. It cannot
    receive a broker or database client through this interface.
    """

    def __init__(self, handler: Callable[[AgentRequest], str | Mapping[str, object]]) -> None:
        self._handler = handler

    def invoke(self, request: AgentRequest) -> AgentCallResult:
        started = time.monotonic()
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self._handler, request)
        try:
            response = future.result(timeout=request.timeout_seconds)
            if isinstance(response, Mapping):
                raw = json.dumps(response, sort_keys=True, separators=(",", ":"))
            elif isinstance(response, str):
                raw = response
            else:
                return AgentCallResult(
                    "invalid_response",
                    None,
                    request.request_hash,
                    int((time.monotonic() - started) * 1000),
                    "handler_returned_unsupported_type",
                )
            if len(raw) > request.max_output_tokens * 16:
                return AgentCallResult(
                    "response_too_large",
                    None,
                    request.request_hash,
                    int((time.monotonic() - started) * 1000),
                    "response_size_limit",
                )
            return AgentCallResult(
                "completed",
                raw,
                request.request_hash,
                int((time.monotonic() - started) * 1000),
            )
        except TimeoutError:
            future.cancel()
            return AgentCallResult(
                "timeout",
                None,
                request.request_hash,
                int((time.monotonic() - started) * 1000),
                "role_deadline_exceeded",
            )
        except Exception as exc:
            return AgentCallResult(
                "failed",
                None,
                request.request_hash,
                int((time.monotonic() - started) * 1000),
                f"{type(exc).__name__}:{exc}",
            )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)


def format_repair_request(
    request: AgentRequest, raw_output: str, errors: list[str]
) -> AgentRequest:
    """Return a next-attempt repair request containing no new evidence."""

    payload = {
        "repair": {
            "original_output": raw_output,
            "schema_errors": list(dict.fromkeys(errors)),
        }
    }
    return AgentRequest(
        role=request.role,
        agent_id=request.agent_id,
        payload=payload,
        timeout_seconds=request.timeout_seconds,
        max_output_tokens=request.max_output_tokens,
        max_cost_usd=request.max_cost_usd,
        attempt=request.attempt + 1,
    )


__all__ = [
    "AgentCallResult",
    "AgentClient",
    "AgentRequest",
    "InProcessAgentClient",
    "format_repair_request",
]
