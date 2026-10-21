from unittest.mock import AsyncMock
import httpx
import pytest
from fastapi.testclient import TestClient
from openai import AuthenticationError, OpenAIError

from app.main import app
from app.models.report import Confidence, Finding, InvestigationReport
from app.services.github_client import GitHubClientError


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_evidence_package():
    return {
        "repository": {
            "full_name": "fastapi/fastapi",
            "description": "FastAPI framework",
            "default_branch": "master",
            "html_url": "https://github.com/fastapi/fastapi",
            "private": False,
        },
        "files_discovered": 10,
        "files_selected": 2,
        "files_retrieved": 2,
        "total_evidence_bytes": 1024,
        "evidence": [
            {
                "path": "main.py",
                "size": 512,
                "content": "from fastapi import FastAPI\napp = FastAPI()",
            },
            {
                "path": "routes.py",
                "size": 512,
                "content": "@app.get('/')\ndef index(): return {}",
            },
        ],
    }


@pytest.fixture
def sample_investigation_report():
    return InvestigationReport(
        summary="Investigation completed. Found standard FastAPI setup.",
        findings=[
            Finding(
                title="Root Route Defined",
                explanation="The application exposes an index route.",
                evidence_paths=["routes.py"],
                confidence=Confidence.HIGH,
            )
        ],
        root_cause_hypotheses=["No bottlenecks found in routes."],
        recommended_next_steps=["Profile endpoint execution times."],
        limitations=["Only 2 files were inspected."],
    )


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "service": "Hawk",
        "version": "0.1.0",
    }


def test_health_details(client):
    response = client.get("/health/details")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("healthy", "degraded")
    assert "database" in data
    assert "redis" in data


def test_create_task_async_submission(client):
    payload = {
        "objective": "Investigate latency in video upload endpoints",
        "repository_url": "https://github.com/fastapi/fastapi",
    }

    # Asynchronous submission returns 202 Accepted and persistent task_id
    response = client.post("/tasks", json=payload)
    assert response.status_code == 202
    data = response.json()

    assert "task_id" in data
    assert data["status"] == "received"
    assert data["objective"] == payload["objective"]
    assert data["repository_url"] == "https://github.com/fastapi/fastapi"
    assert "created_at" in data

    # Verify task details can be retrieved via GET /tasks/{task_id}
    task_id = data["task_id"]
    get_res = client.get(f"/tasks/{task_id}")
    assert get_res.status_code == 200
    task_detail = get_res.json()
    assert task_detail["id"] == task_id
    assert task_detail["objective"] == payload["objective"]


def test_create_task_sync_success(
    client, monkeypatch, sample_evidence_package, sample_investigation_report
):
    mock_collect = AsyncMock(return_value=sample_evidence_package)
    mock_analyze = AsyncMock(return_value=sample_investigation_report)

    monkeypatch.setattr("app.api.tasks.collect_repository_evidence", mock_collect)
    monkeypatch.setattr("app.api.tasks.analyze_engineering_evidence", mock_analyze)

    payload = {
        "objective": "Investigate latency in video upload endpoints",
        "repository_url": "https://github.com/fastapi/fastapi",
    }

    # Synchronous evaluation mode
    response = client.post("/tasks?sync=true", json=payload)

    assert response.status_code == 200
    data = response.json()

    assert "task_id" in data
    assert data["status"] == "completed"
    assert data["objective"] == payload["objective"]
    assert data["repository"]["full_name"] == "fastapi/fastapi"
    assert data["evidence_stats"] == {
        "files_discovered": 10,
        "files_selected": 2,
        "files_retrieved": 2,
        "total_evidence_bytes": 1024,
    }
    assert data["report"]["summary"] == sample_investigation_report.summary
    assert len(data["report"]["findings"]) == 1

    mock_collect.assert_awaited_once_with("fastapi", "fastapi")
    mock_analyze.assert_awaited_once_with(
        objective=payload["objective"],
        repository_name="fastapi/fastapi",
        evidence=sample_evidence_package["evidence"],
    )

    # Verify report endpoint
    report_res = client.get(f"/tasks/{data['task_id']}/report")
    assert report_res.status_code == 200
    report_data = report_res.json()
    assert report_data["summary"] == sample_investigation_report.summary


def test_create_task_handles_git_suffix(
    client, monkeypatch, sample_evidence_package, sample_investigation_report
):
    mock_collect = AsyncMock(return_value=sample_evidence_package)
    mock_analyze = AsyncMock(return_value=sample_investigation_report)

    monkeypatch.setattr("app.api.tasks.collect_repository_evidence", mock_collect)
    monkeypatch.setattr("app.api.tasks.analyze_engineering_evidence", mock_analyze)

    payload = {
        "objective": "Investigate latency in video upload endpoints",
        "repository_url": "https://github.com/fastapi/fastapi.git",
    }

    response = client.post("/tasks?sync=true", json=payload)

    assert response.status_code == 200
    mock_collect.assert_awaited_once_with("fastapi", "fastapi")


def test_create_task_handles_empty_evidence(
    client, monkeypatch, sample_evidence_package
):
    empty_evidence_package = {
        **sample_evidence_package,
        "files_discovered": 5,
        "files_selected": 0,
        "files_retrieved": 0,
        "total_evidence_bytes": 0,
        "evidence": [],
    }

    mock_collect = AsyncMock(return_value=empty_evidence_package)
    mock_analyze = AsyncMock()

    monkeypatch.setattr("app.api.tasks.collect_repository_evidence", mock_collect)
    monkeypatch.setattr("app.api.tasks.analyze_engineering_evidence", mock_analyze)

    payload = {
        "objective": "Investigate repository with no source files",
        "repository_url": "https://github.com/fastapi/fastapi",
    }

    response = client.post("/tasks?sync=true", json=payload)

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "blocked"
    assert data["evidence_stats"]["files_retrieved"] == 0
    assert "no eligible source-file evidence" in data["report"]["summary"].lower()
    assert len(data["report"]["limitations"]) > 0
    mock_analyze.assert_not_called()


def test_create_task_handles_github_failure(client, monkeypatch):
    mock_collect = AsyncMock(
        side_effect=GitHubClientError("Repository not found or not publicly accessible")
    )
    monkeypatch.setattr("app.api.tasks.collect_repository_evidence", mock_collect)

    payload = {
        "objective": "Investigate repository that does not exist",
        "repository_url": "https://github.com/owner/nonexistent",
    }

    response = client.post("/tasks?sync=true", json=payload)

    assert response.status_code == 502
    assert response.json()["detail"] == "Repository not found or not publicly accessible"


def test_create_task_handles_missing_openai_config(
    client, monkeypatch, sample_evidence_package
):
    mock_collect = AsyncMock(return_value=sample_evidence_package)
    mock_analyze = AsyncMock(
        side_effect=RuntimeError(
            "OpenAI API key is missing. Configure OPENAI_API_KEY in .env."
        )
    )

    monkeypatch.setattr("app.api.tasks.collect_repository_evidence", mock_collect)
    monkeypatch.setattr("app.api.tasks.analyze_engineering_evidence", mock_analyze)

    payload = {
        "objective": "Investigate latency in video upload endpoints",
        "repository_url": "https://github.com/fastapi/fastapi",
    }

    response = client.post("/tasks?sync=true", json=payload)

    assert response.status_code == 500
    assert response.json()["detail"] == "OpenAI API key is missing or unconfigured"
    # Ensure secrets and internal file paths are not exposed
    assert ".env" not in response.json()["detail"]


def test_create_task_handles_invalid_openai_auth(
    client, monkeypatch, sample_evidence_package
):
    mock_collect = AsyncMock(return_value=sample_evidence_package)
    mock_analyze = AsyncMock(
        side_effect=AuthenticationError(
            "Incorrect API key provided: sk-invalid...",
            response=httpx.Response(401, request=httpx.Request("POST", "https://api.openai.com")),
            body=None,
        )
    )

    monkeypatch.setattr("app.api.tasks.collect_repository_evidence", mock_collect)
    monkeypatch.setattr("app.api.tasks.analyze_engineering_evidence", mock_analyze)

    payload = {
        "objective": "Investigate latency in video upload endpoints",
        "repository_url": "https://github.com/fastapi/fastapi",
    }

    response = client.post("/tasks?sync=true", json=payload)

    assert response.status_code == 500
    assert response.json()["detail"] == "Reasoning service authentication failed"
    # Ensure raw secret is not leaked in error response
    assert "sk-" not in response.json()["detail"]


def test_create_task_handles_openai_failure(
    client, monkeypatch, sample_evidence_package
):
    mock_collect = AsyncMock(return_value=sample_evidence_package)
    mock_analyze = AsyncMock(
        side_effect=OpenAIError("Rate limit exceeded")
    )

    monkeypatch.setattr("app.api.tasks.collect_repository_evidence", mock_collect)
    monkeypatch.setattr("app.api.tasks.analyze_engineering_evidence", mock_analyze)

    payload = {
        "objective": "Investigate latency in video upload endpoints",
        "repository_url": "https://github.com/fastapi/fastapi",
    }

    response = client.post("/tasks?sync=true", json=payload)

    assert response.status_code == 502
    assert response.json()["detail"] == "Reasoning service request failed"


def test_create_task_rejects_empty_repo_after_git_stripped(client):
    payload = {
        "objective": "Investigate repository with invalid name",
        "repository_url": "https://github.com/owner/.git",
    }

    response = client.post("/tasks", json=payload)
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid repository owner or repository name"


def test_auth_and_user_flow(client):
    # Register new user
    import time
    unique_email = f"user_{int(time.time())}@example.com"
    reg_payload = {
        "email": unique_email,
        "password": "Password123!",
        "name": "Test User",
    }
    reg_res = client.post("/auth/register", json=reg_payload)
    assert reg_res.status_code == 201
    auth_data = reg_res.json()
    assert "access_token" in auth_data
    assert auth_data["user"]["email"] == unique_email

    token = auth_data["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Verify /auth/me
    me_res = client.get("/auth/me", headers=headers)
    assert me_res.status_code == 200
    assert me_res.json()["email"] == unique_email

    # Submit task with user token
    task_res = client.post(
        "/tasks",
        headers=headers,
        json={
            "objective": "Investigate user specific task processing",
            "repository_url": "https://github.com/fastapi/fastapi",
        },
    )
    assert task_res.status_code == 202
    task_id = task_res.json()["task_id"]

    # Verify listing tasks returns the task
    list_res = client.get("/tasks", headers=headers)
    assert list_res.status_code == 200
    task_ids = [t["id"] for t in list_res.json()]
    assert task_id in task_ids

    # Cancel task
    cancel_res = client.post(f"/tasks/{task_id}/cancel", headers=headers)
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "cancelled"
