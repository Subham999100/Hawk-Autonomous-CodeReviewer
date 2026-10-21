import json
from unittest.mock import AsyncMock, patch
import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.report import Confidence, Finding, InvestigationReport
from app.services.jev_service import orchestrate_investigation_triage
from app.services.obsidian_service import format_investigation_note, sync_investigation_memory
from app.services.worker import process_task


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.asyncio
async def test_jev_service_fallback_heuristic():
    decision = await orchestrate_investigation_triage(
        objective="Investigate high memory leak and slow latency in worker threads",
        repository_name="test/repo",
        tree_sample=["main.py", "worker.py"],
    )
    assert decision["status"] == "fallback"
    assert decision["answers"]["investigation_scope"]["decision"] == "performance_bottleneck"
    assert decision["answers"]["requires_deep_retrieval"]["decision"] is True


@pytest.mark.asyncio
async def test_jev_service_real_api_mock(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.jev_api_key", "mock-jev-key")

    mock_resp = httpx.Response(
        200,
        json={
            "answers": {
                "investigation_scope": {"decision": "security_vulnerability", "confidence": 0.95},
                "requires_deep_retrieval": {"decision": True, "probability": 0.99},
                "complexity_score": {"level": "critical", "score": 0.92},
            }
        },
        request=httpx.Request("POST", "https://api.typesafe.ai/v1/systemone"),
    )

    async def mock_post(self, url, **kwargs):
        return mock_resp

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    decision = await orchestrate_investigation_triage(
        objective="Analyze authentication bypass in token validation",
        repository_name="auth/service",
        tree_sample=["auth.py", "jwt.py"],
    )

    assert decision["status"] == "success"
    assert decision["provider"] == "typesafe_jev"
    assert decision["answers"]["investigation_scope"]["decision"] == "security_vulnerability"


@pytest.mark.asyncio
async def test_obsidian_service_note_formatting_and_sync(monkeypatch):
    sample_report = InvestigationReport(
        summary="Found potential SQL injection in search endpoint.",
        findings=[
            Finding(
                title="Unescaped Query Parameter",
                explanation="The query string is formatted directly into SQL query.",
                evidence_paths=["app/db.py"],
                confidence=Confidence.HIGH,
            )
        ],
        root_cause_hypotheses=["Dynamic string concatenation without parameterization."],
        recommended_next_steps=["Refactor query to use SQLAlchemy parameterized queries."],
        limitations=["Only inspected 1 database file."],
    )

    note = format_investigation_note(
        task_id="task-12345",
        objective="Audit SQL query safety",
        repository_name="corp/db-service",
        report=sample_report,
    )

    assert "task_id: \"task-12345\"" in note
    assert "Unescaped Query Parameter" in note
    assert "app/db.py" in note

    # Test sync when OBSIDIAN_API_KEY is not set -> stores locally
    monkeypatch.setattr("app.core.config.settings.obsidian_api_key", "")
    res = await sync_investigation_memory(
        task_id="task-12345",
        objective="Audit SQL query safety",
        repository_name="corp/db-service",
        report=sample_report,
    )
    assert res["status"] == "local_memory_stored"
    assert res["synced_to_vault"] is False


def test_sse_endpoint_replays_events(client):
    # Submit task
    res = client.post(
        "/tasks",
        json={
            "objective": "Investigate connection timeout in async client",
            "repository_url": "https://github.com/fastapi/fastapi",
        },
    )
    assert res.status_code == 202
    task_id = res.json()["task_id"]

    # Connect to SSE endpoint with stream context
    with client.stream("GET", f"/tasks/{task_id}/events") as sse_res:
        assert sse_res.status_code == 200
        assert "text/event-stream" in sse_res.headers["content-type"]
        for line in sse_res.iter_lines():
            if line:
                assert "id:" in line or "event:" in line or "data:" in line
                break
