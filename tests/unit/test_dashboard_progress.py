from pathlib import Path

from fastapi.testclient import TestClient


def _authenticated_client(tmp_path: Path, monkeypatch) -> TestClient:
    from kalshi_bot.config import settings as settings_mod

    monkeypatch.setenv("DB_PATH", str(tmp_path / "progress.db"))
    monkeypatch.setenv("PAPER_TRADING", "true")
    settings_mod.get_settings.cache_clear()

    from kalshi_bot.web.app import create_app

    client = TestClient(create_app(bootstrap_token="progress-bootstrap"))
    response = client.post("/_auth/bootstrap", json={"token": "progress-bootstrap"})
    assert response.status_code == 204
    return client


def test_progress_page_is_detailed_and_links_evidence_export(tmp_path, monkeypatch):
    client = _authenticated_client(tmp_path, monkeypatch)
    try:
        response = client.get("/progress")
        assert response.status_code == 200
        assert "Build &amp; data progress" in response.text
        assert "Setup" in response.text
        assert "Data collection" in response.text
        assert "Testing &amp; validation" in response.text
        assert "What is running now" in response.text
        assert "Paper engine" in response.text
        assert "Current evidence" in response.text
        assert "What\u2019s left" in response.text
        assert "/exports/progress.json" in response.text
    finally:
        from kalshi_bot.config import settings as settings_mod

        settings_mod.get_settings.cache_clear()


def test_progress_export_is_downloadable_and_redacted(tmp_path, monkeypatch):
    client = _authenticated_client(tmp_path, monkeypatch)
    try:
        response = client.get("/exports/progress.json")
        assert response.status_code == 200
        assert "attachment" in response.headers["content-disposition"]
        payload = response.json()
        assert payload["schema_version"] == "dashboard-progress-v1"
        assert {stage["key"] for stage in payload["progress"]["stages"]} == {
            "setup",
            "collection",
            "testing",
        }
        assert "feeds" in payload
        assert "test_jobs" in payload
        assert "private_key" not in response.text.lower()
    finally:
        from kalshi_bot.config import settings as settings_mod

        settings_mod.get_settings.cache_clear()


def test_unknown_job_output_is_not_exposed(tmp_path, monkeypatch):
    client = _authenticated_client(tmp_path, monkeypatch)
    try:
        assert client.get("/operations/not-a-job/output").status_code == 404
    finally:
        from kalshi_bot.config import settings as settings_mod

        settings_mod.get_settings.cache_clear()
