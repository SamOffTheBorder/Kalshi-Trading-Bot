import json

import httpx
import pytest

from kalshi_bot.agents.a2a import (
    VERDICT_MEDIA_TYPE,
    A2AAgentClient,
    A2AOperatorSwitch,
    A2ASecurityError,
    A2AUpdateProcessor,
)
from kalshi_bot.agents.gateway import AgentRequest, InProcessAgentClient


def _request(timeout=1.0):
    return AgentRequest("skeptic", "run-1:skeptic", {"evidence_ids": ["e1"]}, timeout, 100, 1)


def _card(**updates):
    card = {
        "name": "fixture-agent",
        "description": "Evidence-bound council reviewer",
        "version": "1",
        "protocolVersion": "1.0",
        "supportedInterfaces": [
            {
                "url": "https://agent.test/a2a",
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            }
        ],
        "skills": [{"id": "council/skeptic", "name": "Council skeptic"}],
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "capabilities": {"streaming": False},
        "securitySchemes": {"bearer": {"type": "http"}},
    }
    card.update(updates)
    return card


def test_a2a_discovers_card_submits_versioned_task_and_extracts_only_artifact():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=_card())
        payload = json.loads(request.content)
        if payload["method"] == "message/send":
            return httpx.Response(200, json={"result": {"task": {"id": "task-1"}}})
        if payload["method"] == "tasks/get":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "id": "task-1",
                        "status": "completed",
                        "artifacts": [
                            {
                                "artifactId": "artifact-1",
                                "mediaType": VERDICT_MEDIA_TYPE,
                                "parts": [{"text": '{"decision":"support"}'}],
                            }
                        ],
                    }
                },
            )
        raise AssertionError(payload["method"])

    client = A2AAgentClient(
        agent_card_uri="https://agent.test/.well-known/agent-card.json",
        expected_skill="council/skeptic",
        allowed_hosts=("agent.test",),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        auth_headers=lambda: {"Authorization": "Bearer secret"},
        sleep_fn=lambda _seconds: None,
    )
    result = client.invoke(_request())

    assert result.status == "completed"
    assert result.raw_output == '{"decision":"support"}'
    assert client.card is not None
    assert client.card.protocol_version == "1.0"
    assert len(client.card_snapshots) == 1
    assert all(request.headers["A2A-Version"] == "1.0" for request in requests)
    post = next(request for request in requests if request.method == "POST")
    assert post.headers["Idempotency-Key"] == _request().request_hash
    assert "secret" not in json.dumps(client.card.raw_card)


@pytest.mark.parametrize(
    "card_update, message",
    [
        ({"protocolVersion": "0.3"}, "A2A 1.0"),
        ({"skills": []}, "assigned council skill"),
        (
            {"skills": [{"id": "council/skeptic", "description": "can place orders"}]},
            "forbidden capability",
        ),
    ],
)
def test_a2a_rejects_unsupported_or_unsafe_agent_cards(card_update, message):
    def handler(request):
        return httpx.Response(200, json=_card(**card_update))

    client = A2AAgentClient(
        agent_card_uri="https://agent.test/card",
        expected_skill="council/skeptic",
        allowed_hosts=("agent.test",),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(A2ASecurityError, match=message):
        client.discover()


def test_a2a_missing_artifact_and_redirect_fail_closed():
    def no_artifact(request):
        if request.method == "GET":
            return httpx.Response(200, json=_card())
        payload = json.loads(request.content)
        if payload["method"] == "message/send":
            return httpx.Response(200, json={"result": {"task": {"id": "task-1"}}})
        return httpx.Response(
            200,
            json={
                "result": {
                    "id": "task-1",
                    "status": "completed",
                    "messages": [{"text": "take"}],
                }
            },
        )

    client = A2AAgentClient(
        agent_card_uri="https://agent.test/card",
        expected_skill="council/skeptic",
        allowed_hosts=("agent.test",),
        client=httpx.Client(transport=httpx.MockTransport(no_artifact)),
    )
    result = client.invoke(_request())
    assert result.status == "failed"
    assert result.error == "missing_verdict_artifact"

    redirect = A2AAgentClient(
        agent_card_uri="https://agent.test/card",
        expected_skill="council/skeptic",
        allowed_hosts=("agent.test",),
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(302, headers={"location": "https://other.test/card"})
            )
        ),
    )
    with pytest.raises(A2ASecurityError, match="redirect"):
        redirect.discover()


def test_a2a_timeout_cancels_remote_task_and_update_processor_is_idempotent():
    methods = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json=_card())
        payload = json.loads(request.content)
        methods.append(payload["method"])
        if payload["method"] == "message/send":
            return httpx.Response(200, json={"result": {"task": {"id": "task-1"}}})
        if payload["method"] == "tasks/get":
            return httpx.Response(200, json={"result": {"id": "task-1", "status": "working"}})
        return httpx.Response(200, json={"result": {"id": "task-1", "status": "canceled"}})

    client = A2AAgentClient(
        agent_card_uri="https://agent.test/card",
        expected_skill="council/skeptic",
        allowed_hosts=("agent.test",),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep_fn=lambda _seconds: None,
    )
    result = client.invoke(_request(timeout=0.001))
    assert result.status == "timeout"
    assert "tasks/cancel" in methods

    processor = A2AUpdateProcessor("task-1")
    assert processor.process({"id": "task-1", "updateId": "u1", "sequence": 1}) == "accepted"
    assert processor.process({"id": "task-1", "updateId": "u1", "sequence": 1}) == "duplicate"
    with pytest.raises(A2ASecurityError, match="task ID"):
        processor.process({"id": "other", "updateId": "u2"})


def test_a2a_operator_switch_uses_explicit_in_process_fallback():
    remote = InProcessAgentClient(lambda request: "remote")
    fallback = InProcessAgentClient(lambda request: "fallback")
    assert A2AOperatorSwitch(enabled=False).select(remote, fallback) is fallback
    assert A2AOperatorSwitch(enabled=True).select(remote, fallback) is remote
