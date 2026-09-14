"""Restricted A2A 1.0 transport adapter for council artifacts.

The trading domain talks to :class:`AgentClient`; this module owns protocol
headers, Agent Card validation, task polling, duplicate delivery handling, and
the explicit no-execution capability policy.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx

from kalshi_bot.agents.gateway import AgentCallResult, AgentClient, AgentRequest

A2A_PROTOCOL_VERSION = "1.0"
VERDICT_MEDIA_TYPE = "application/vnd.kalshi.council.verdict+json;version=1"
_FORBIDDEN_CAPABILITY_WORDS = (
    "order",
    "credential",
    "secret",
    "policy",
    "lifecycle",
    "bankroll",
    "risk_state",
)


class A2ASecurityError(RuntimeError):
    """The remote card or endpoint violates the configured security policy."""


@dataclass(frozen=True)
class AgentCardSnapshot:
    name: str
    version: str
    url: str
    protocol_version: str
    skills: tuple[str, ...]
    input_modes: tuple[str, ...]
    output_modes: tuple[str, ...]
    capabilities: Mapping[str, object]
    security_schemes: tuple[str, ...]
    card_hash: str
    raw_card: Mapping[str, object]


@dataclass(frozen=True)
class A2ATask:
    task_id: str
    request_hash: str
    role: str
    status: str
    artifact: str | None = None
    error: str | None = None


@dataclass
class A2AUpdateProcessor:
    """Process task updates once, in sequence, for one expected task."""

    expected_task_id: str
    _seen: set[str] = field(default_factory=set, init=False)
    _last_sequence: int = field(default=-1, init=False)

    def process(self, update: Mapping[str, object]) -> str:
        task_id = str(update.get("id") or update.get("taskId") or "")
        if task_id != self.expected_task_id:
            raise A2ASecurityError("A2A task ID mismatch")
        update_id = str(update.get("updateId") or update.get("artifactId") or task_id)
        if update_id in self._seen:
            return "duplicate"
        sequence = update.get("sequence")
        if sequence is not None:
            try:
                sequence_value = int(str(sequence))
            except (TypeError, ValueError) as exc:
                raise A2ASecurityError("A2A task update sequence is invalid") from exc
            if sequence_value < self._last_sequence:
                raise A2ASecurityError("A2A task update arrived out of order")
            self._last_sequence = sequence_value
        self._seen.add(update_id)
        return "accepted"


class A2AAgentClient(AgentClient):
    """A synchronous, allowlisted A2A 1.0 client with typed artifact output."""

    def __init__(
        self,
        *,
        agent_card_uri: str,
        expected_skill: str,
        allowed_hosts: Sequence[str],
        client: httpx.Client | None = None,
        auth_headers: Callable[[], Mapping[str, str]] | None = None,
        require_card_signature: bool = False,
        verify_card_signature: Callable[[Mapping[str, object]], bool] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self._card_uri = agent_card_uri
        self._expected_skill = expected_skill
        self._allowed_hosts = frozenset(allowed_hosts)
        self._client = client or httpx.Client(follow_redirects=False)
        self._auth_headers = auth_headers
        self._require_signature = require_card_signature
        self._verify_signature = verify_card_signature
        self._clock = clock
        self._sleep = sleep_fn
        self._card: AgentCardSnapshot | None = None
        self._tasks: dict[str, A2ATask] = {}
        self.card_snapshots: list[AgentCardSnapshot] = []

    @property
    def card(self) -> AgentCardSnapshot | None:
        return self._card

    def discover(self) -> AgentCardSnapshot:
        body = self._get_json(self._card_uri)
        card = self._validate_card(body, self._card_uri)
        self._card = card
        self.card_snapshots.append(card)
        return card

    def submit_task(self, request: AgentRequest) -> A2ATask:
        existing = self._tasks.get(request.request_hash)
        if existing is not None:
            return existing
        card = self._card or self.discover()
        message = {
            "messageId": str(uuid.uuid4()),
            "role": "user",
            "parts": [{"kind": "text", "text": json.dumps(request.payload, sort_keys=True)}],
            "metadata": {
                "councilRunId": request.agent_id.split(":", 1)[0],
                "role": request.role,
                "attempt": request.attempt,
                "requestHash": request.request_hash,
            },
        }
        result = self._rpc(
            card.url,
            "message/send",
            {"message": message},
            request=request,
        )
        task_id = self._task_id(result)
        task = A2ATask(task_id, request.request_hash, request.role, "submitted")
        self._tasks[request.request_hash] = task
        return task

    def get_task(self, task_id: str, request: AgentRequest) -> Mapping[str, object]:
        card = self._card or self.discover()
        return self._rpc(card.url, "tasks/get", {"id": task_id}, request=request)

    def cancel_task(self, task_id: str, request: AgentRequest) -> Mapping[str, object]:
        card = self._card or self.discover()
        return self._rpc(card.url, "tasks/cancel", {"id": task_id}, request=request)

    def retrieve_artifact(self, task: Mapping[str, object]) -> str | None:
        raw_artifacts: object = task.get("artifacts")
        if raw_artifacts is None:
            result = task.get("result")
            if isinstance(result, Mapping):
                raw_artifacts = result.get("artifacts")
        if not isinstance(raw_artifacts, list):
            return None
        for artifact in raw_artifacts:
            if not isinstance(artifact, Mapping):
                continue
            media_type = artifact.get("mediaType") or artifact.get("media_type")
            if media_type != VERDICT_MEDIA_TYPE:
                continue
            parts = artifact.get("parts") or []
            if not isinstance(parts, list):
                continue
            for part in parts:
                if isinstance(part, Mapping) and isinstance(part.get("text"), str):
                    return part["text"]
                if isinstance(part, Mapping) and isinstance(part.get("data"), str):
                    return part["data"]
        return None

    def invoke(self, request: AgentRequest) -> AgentCallResult:
        started = self._clock()
        try:
            task = self.submit_task(request)
            processor = A2AUpdateProcessor(task.task_id)
            while self._clock() - started <= request.timeout_seconds:
                update = self.get_task(task.task_id, request)
                processor.process(update)
                status = str(update.get("status") or update.get("state") or "working").lower()
                artifact = self.retrieve_artifact(update)
                if status in {"completed", "failed", "canceled", "cancelled", "rejected"}:
                    if status == "completed" and artifact is None:
                        return self._result(
                            "failed", None, request, started, "missing_verdict_artifact"
                        )
                    return self._result(
                        "completed" if status == "completed" else "failed",
                        artifact,
                        request,
                        started,
                        None if status == "completed" else f"remote_task_{status}",
                    )
                self._sleep(min(0.05, max(0.0, request.timeout_seconds / 10)))
            self.cancel_task(task.task_id, request)
            return self._result("timeout", None, request, started, "remote_task_deadline")
        except A2ASecurityError as exc:
            return self._result("failed", None, request, started, f"security:{exc}")
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            return self._result(
                "failed",
                None,
                request,
                started,
                f"transport:{type(exc).__name__}:{exc}",
            )

    def _result(
        self,
        status: str,
        raw: str | None,
        request: AgentRequest,
        started: float,
        error: str | None,
    ) -> AgentCallResult:
        return AgentCallResult(
            status,
            raw,
            request.request_hash,
            int((self._clock() - started) * 1000),
            error,
        )

    def _validate_card(
        self, card: Mapping[str, object], source_uri: str
    ) -> AgentCardSnapshot:
        if not isinstance(card, Mapping):
            raise A2ASecurityError("Agent Card is not an object")
        self._validate_url(source_uri)
        name = str(card.get("name") or "")
        version = str(card.get("version") or "")
        if not name or not version:
            raise A2ASecurityError("Agent Card identity is incomplete")
        if self._require_signature and (
            self._verify_signature is None or not self._verify_signature(card)
        ):
            raise A2ASecurityError("Agent Card signature requirement failed")
        protocol_version = str(card.get("protocolVersion") or A2A_PROTOCOL_VERSION)
        raw_interfaces = card.get("supportedInterfaces")
        interfaces = raw_interfaces if isinstance(raw_interfaces, list) else []
        urls: list[str] = []
        interface_versions: list[str] = []
        for interface in interfaces:
            if not isinstance(interface, Mapping):
                continue
            if interface.get("url"):
                urls.append(str(interface["url"]))
            if interface.get("protocolVersion"):
                interface_versions.append(str(interface["protocolVersion"]))
        endpoint = urls[0] if urls else str(card.get("url") or source_uri)
        endpoint = urljoin(source_uri, endpoint)
        self._validate_url(endpoint)
        versions = set(interface_versions or [protocol_version])
        if protocol_version != A2A_PROTOCOL_VERSION or versions != {A2A_PROTOCOL_VERSION}:
            raise A2ASecurityError("Agent Card does not support A2A 1.0")
        raw_skills = card.get("skills")
        skills = raw_skills if isinstance(raw_skills, list) else []
        skill_ids = tuple(
            str(skill.get("id"))
            for skill in skills
            if isinstance(skill, Mapping) and skill.get("id")
        )
        if self._expected_skill not in skill_ids:
            raise A2ASecurityError("assigned council skill is not declared")
        for skill in skills:
            if not isinstance(skill, Mapping):
                continue
            text = json.dumps(skill, sort_keys=True).casefold()
            if any(word in text for word in _FORBIDDEN_CAPABILITY_WORDS):
                raise A2ASecurityError("Agent Card declares a forbidden capability")
        raw_input_modes = card.get("defaultInputModes")
        raw_output_modes = card.get("defaultOutputModes")
        input_modes = (
            tuple(str(value) for value in raw_input_modes)
            if isinstance(raw_input_modes, list)
            else ()
        )
        output_modes = (
            tuple(str(value) for value in raw_output_modes)
            if isinstance(raw_output_modes, list)
            else ()
        )
        if "application/json" not in input_modes or "application/json" not in output_modes:
            raise A2ASecurityError("Agent Card lacks JSON input/output media types")
        raw_security = card.get("securitySchemes")
        security = raw_security if isinstance(raw_security, Mapping) else {}
        if not isinstance(raw_security, Mapping):
            raise A2ASecurityError("Agent Card security schemes are invalid")
        raw_capabilities = card.get("capabilities")
        capabilities = (
            raw_capabilities if isinstance(raw_capabilities, Mapping) else {}
        )
        canonical = json.dumps(card, sort_keys=True, separators=(",", ":"), default=str)
        return AgentCardSnapshot(
            name=name,
            version=version,
            url=endpoint,
            protocol_version=A2A_PROTOCOL_VERSION,
            skills=skill_ids,
            input_modes=input_modes,
            output_modes=output_modes,
            capabilities=capabilities,
            security_schemes=tuple(str(key) for key in security),
            card_hash=hashlib.sha256(canonical.encode()).hexdigest(),
            raw_card=card,
        )

    def _validate_url(self, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname:
            raise A2ASecurityError("A2A endpoints must use HTTPS")
        if parsed.hostname not in self._allowed_hosts:
            raise A2ASecurityError(f"A2A host is not allowlisted: {parsed.hostname}")
        return value

    def _get_json(self, url: str) -> Mapping[str, object]:
        self._validate_url(url)
        response = self._client.get(url, headers=self._headers())
        if 300 <= response.status_code < 400:
            location = response.headers.get("location")
            if not location or urlparse(urljoin(url, location)).hostname not in self._allowed_hosts:
                raise A2ASecurityError("A2A redirect leaves the host allowlist")
            raise A2ASecurityError("A2A redirects require explicit endpoint configuration")
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, Mapping):
            raise ValueError("A2A response is not an object")
        return body

    def _rpc(
        self,
        url: str,
        method: str,
        params: Mapping[str, object],
        *,
        request: AgentRequest,
    ) -> Mapping[str, object]:
        self._validate_url(url)
        response = self._client.post(
            url,
            headers={**self._headers(), "Idempotency-Key": request.request_hash},
            json={"jsonrpc": "2.0", "id": request.request_hash, "method": method, "params": params},
            timeout=request.timeout_seconds,
        )
        if 300 <= response.status_code < 400:
            raise A2ASecurityError("A2A task redirect is not permitted")
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, Mapping):
            raise ValueError("A2A RPC response is not an object")
        if body.get("error"):
            raise ValueError(f"A2A RPC error: {body['error']}")
        result = body.get("result", body)
        if not isinstance(result, Mapping):
            raise ValueError("A2A RPC result is not an object")
        return result

    def _headers(self) -> dict[str, str]:
        headers = {"A2A-Version": A2A_PROTOCOL_VERSION, "Accept": "application/json"}
        if self._auth_headers is not None:
            headers.update(self._auth_headers())
        return headers

    @staticmethod
    def _task_id(result: Mapping[str, object]) -> str:
        task = result.get("task")
        if isinstance(task, Mapping) and task.get("id"):
            return str(task["id"])
        if result.get("id"):
            return str(result["id"])
        raise ValueError("A2A response omitted task ID")


@dataclass(frozen=True)
class A2AOperatorSwitch:
    """Explicit remote switch with a caller-provided safe fallback."""

    enabled: bool = False

    def select(self, remote: AgentClient, fallback: AgentClient) -> AgentClient:
        return remote if self.enabled else fallback


__all__ = [
    "A2A_PROTOCOL_VERSION",
    "VERDICT_MEDIA_TYPE",
    "A2AAgentClient",
    "A2AOperatorSwitch",
    "A2ASecurityError",
    "A2ATask",
    "A2AUpdateProcessor",
    "AgentCardSnapshot",
]
