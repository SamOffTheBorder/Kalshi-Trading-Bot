"""Authentication boundary for the local dashboard."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def dashboard_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "dashboard-auth.db"))
    monkeypatch.setenv("KALSHI_KEY_ID", "test-key")
    from kalshi_bot.config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    from kalshi_bot.web.app import create_app

    yield create_app(bootstrap_token="single-use-bootstrap")
    settings_mod.get_settings.cache_clear()


def test_unauthenticated_navigation_and_fragment_fail_closed(dashboard_app):
    client = TestClient(dashboard_app)
    navigation = client.get("/", follow_redirects=False)
    assert navigation.status_code == 303
    assert navigation.headers["location"] == "/login"
    assert (
        client.get("/fragments/overview-status", headers={"X-Dashboard-Refresh": "1"}).status_code
        == 401
    )


def test_bootstrap_uses_fragment_page_and_single_use_exchange(dashboard_app):
    client = TestClient(dashboard_app)
    page = client.get("/_auth/bootstrap")
    assert page.status_code == 200
    assert "Cache-Control" in page.headers and page.headers["cache-control"] == "no-store"
    assert "bootstrap-status" in page.text

    exchange = client.post("/_auth/bootstrap", json={"token": "single-use-bootstrap"})
    assert exchange.status_code == 204
    assert "kalshi_dashboard_session" in client.cookies
    assert client.get("/").status_code == 200
    assert (
        client.post("/_auth/bootstrap", json={"token": "single-use-bootstrap"}).status_code == 401
    )


def test_mutation_requires_same_origin_and_session_csrf(dashboard_app):
    client = TestClient(dashboard_app)
    assert (
        client.post("/_auth/bootstrap", json={"token": "single-use-bootstrap"}).status_code == 204
    )
    csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/").text).group(1)

    assert client.post("/control/kill", data={"csrf_token": csrf_token}).status_code == 403
    assert (
        client.post(
            "/control/kill",
            data={"csrf_token": "wrong"},
            headers={"Origin": "http://testserver"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/control/kill",
            data={"csrf_token": csrf_token},
            headers={"Origin": "http://testserver"},
            follow_redirects=False,
        ).status_code
        == 303
    )


def test_secret_login_uses_a_secure_cookie_for_tls(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "dashboard-login.db"))
    monkeypatch.setenv("KALSHI_KEY_ID", "test-key")
    monkeypatch.setenv("DASHBOARD_AUTH_SECRET", "local-test-secret")
    from kalshi_bot.config import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    from kalshi_bot.web.app import create_app

    try:
        client = TestClient(create_app(secure_cookies=True), base_url="https://testserver")
        assert client.post("/login", data={"secret": "wrong"}).status_code == 401
        response = client.post(
            "/login", data={"secret": "local-test-secret"}, follow_redirects=False
        )
        assert response.status_code == 303
        assert "Secure" in response.headers["set-cookie"]
        assert client.get("/").status_code == 200
    finally:
        settings_mod.get_settings.cache_clear()
