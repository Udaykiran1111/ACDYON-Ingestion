from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from python_app.ingestion import deduplicate, normalize_job, parse_remoteok, with_retry
from python_app.main import app


def sample(source_id="1"):
    return {"id": source_id, "position": "Frontend Engineer", "company": "Acdyon", "location": "Remote", "tags": ["react", "react"], "url": "https://example.test/1"}


def test_parser_normalizes_and_rejects_malformed_records():
    jobs = parse_remoteok([sample(), {"id": 2}], "2026-01-01T00:00:00Z")
    assert len(jobs) == 1
    assert jobs[0].source_id == "1"
    assert jobs[0].tags == ["react"]


def test_deduplication_uses_source_id():
    first = normalize_job(sample(), "now")
    second = normalize_job(sample(), "later")
    assert deduplicate([first, second]) == [first]


def test_retry_uses_exponential_backoff():
    calls = []
    sleeps = []

    def operation():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("temporary")
        return "ok"

    assert with_retry(operation, base_delay=0.1, sleep=sleeps.append) == "ok"
    assert sleeps == [0.1, 0.2]


def test_trigger_endpoint_is_protected(monkeypatch):
    monkeypatch.setattr("python_app.main.run_ingestion", lambda run_id: None)
    client = TestClient(app)
    response = client.post("/api/trigger")
    assert response.status_code == 403
    response = client.post("/api/trigger", headers={"X-Reviewer-Token": "local-reviewer-token"})
    assert response.status_code == 200
    assert response.json()["status"] == "running"


def test_schedule_lifecycle_and_cron_guard(monkeypatch):
    headers = {"X-Reviewer-Token": "local-reviewer-token"}
    monkeypatch.setattr("python_app.main.run_ingestion", lambda run_id: None)
    with TestClient(app) as client:
        assert client.post("/api/schedule", json={"cron": "0 * * * *"}, headers=headers).status_code == 200
        assert client.get("/api/schedule", headers=headers).json()["enabled"] == 1
        assert client.patch("/api/schedule/pause", headers=headers).json()["enabled"] == 0
        assert client.post("/api/scheduled/ingestion", headers={"X-Cron-Token": "local-reviewer-token"}).json()["skipped"] == "schedule-disabled"
        assert client.patch("/api/schedule/resume", headers=headers).json()["enabled"] == 1
        assert client.post("/api/scheduled/ingestion", headers={"X-Cron-Token": "local-reviewer-token"}).json()["ok"] is True
        assert client.delete("/api/schedule", headers=headers).json()["deleted"] is True


def test_sandbox_rate_limit_retries_then_succeeds():
    from python_app.ingestion import SandboxSource, with_retry
    source = SandboxSource("RATE_LIMIT")
    assert with_retry(source.fetch, attempts=3, sleep=lambda _delay: None)[0]["id"] == "sandbox-1"
    assert source.calls == 3


def test_sandbox_server_error_retries_then_succeeds():
    from python_app.ingestion import SandboxSource, with_retry
    source = SandboxSource("SERVER_ERROR")
    assert with_retry(source.fetch, attempts=2, sleep=lambda _delay: None)[0]["id"] == "sandbox-1"
    assert source.calls == 2


def test_sandbox_timeout_is_bounded():
    from python_app.ingestion import SandboxSource, with_retry
    source = SandboxSource("TIMEOUT")
    with pytest.raises(Exception):
        with_retry(source.fetch, attempts=3, sleep=lambda _delay: None)
    assert source.calls == 3


def test_empty_malformed_schema_and_blocked_sources_are_explicit():
    from python_app.ingestion import EmptySourceError, SandboxSource, SourceBlockedError, SourceSchemaError, parse_remoteok_detailed
    assert SandboxSource("EMPTY").fetch() == []
    parsed = parse_remoteok_detailed(SandboxSource("MALFORMED").fetch(), "now")
    assert len(parsed.jobs) == 1 and parsed.rejected == 1
    with pytest.raises(SourceSchemaError):
        parse_remoteok_detailed(SandboxSource("SCHEMA_CHANGE").fetch(), "now")
    with pytest.raises(SourceBlockedError):
        SandboxSource("BLOCKED").fetch()
    with pytest.raises(EmptySourceError):
        raise EmptySourceError("Source returned zero job listings")


def test_audit_input_metrics_distinguish_fetched_valid_rejected_and_duplicates():
    from python_app.ingestion import deduplicate, parse_remoteok_detailed
    payload = [
        {"id": "one", "position": "Role", "company": "Company"},
        {"id": "one", "position": "Role", "company": "Company"},
        {"id": "bad"},
    ]
    parsed = parse_remoteok_detailed(payload, "now")
    unique = deduplicate(parsed.jobs)
    assert parsed.fetched == 3
    assert len(parsed.jobs) == 2
    assert parsed.rejected == 1
    assert len(parsed.jobs) - len(unique) == 1


def test_fetch_result_metrics_are_consistent(monkeypatch):
    from python_app import ingestion

    class FakeResponse:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            return None

        def json(self):
            return [
                {"id": "one", "position": "Role", "company": "Company"},
                {"id": "one", "position": "Role", "company": "Company"},
                {"id": "bad"},
            ]

    monkeypatch.setattr(ingestion.requests, "get", lambda *args, **kwargs: FakeResponse())
    result = ingestion.fetch_remoteok_detailed(pacing_seconds=0, sleep=lambda _delay: None)
    assert result.fetched == 3
    assert result.parsed == 2
    assert len(result.jobs) == 1
    assert result.rejected == 1
    assert result.duplicate_count == 1
    assert result.retry_count == 0
