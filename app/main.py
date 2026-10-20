
from uuid import uuid4

from fastapi import FastAPI, HTTPException

from app.models.task import TaskRequest
from app.services.github_client import (
    GitHubClientError,
    get_repository_metadata,
)

app = FastAPI(
    title="Hawk",
    description="Autonomous Engineering System",
    version="0.1.0",
)


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "Hawk",
        "version": "0.1.0",
    }


@app.post("/tasks", status_code=202)
async def create_task(task: TaskRequest):
    repository_path = task.repository_url.path.strip("/").split("/")
    owner, repo = repository_path

    if repo.endswith(".git"):
        repo = repo[:-4]

    try:
        repository = await get_repository_metadata(owner, repo)
    except GitHubClientError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    return {
        "task_id": str(uuid4()),
        "status": "received",
        "objective": task.objective,
        "repository": repository,
    }
