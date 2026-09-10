from kalshi_bot.web.export import redact_export


def test_export_redaction_preserves_provenance_and_removes_secrets():
    report = redact_export({"source_url": "https://example.test", "api_token": "nope", "nested": {"private_key": "pem"}})
    assert report["source_url"] == "https://example.test"
    assert report["api_token"] == "[REDACTED]"
    assert report["nested"]["private_key"] == "[REDACTED]"
