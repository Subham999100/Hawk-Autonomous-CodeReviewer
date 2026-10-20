
import pytest
from pydantic import ValidationError

from app.models.task import TaskRequest


def test_accepts_valid_github_repository():
    task = TaskRequest(
        objective="Investigate slow video uploads",
        repository_url="https://github.com/fastapi/fastapi",
    )

    assert task.repository_url.host == "github.com"


def test_rejects_non_github_host():
    with pytest.raises(ValidationError):
        TaskRequest(
            objective="Investigate slow video uploads",
            repository_url="https://example.com/owner/repo",
        )


def test_rejects_repository_url_without_owner_and_repo():
    with pytest.raises(ValidationError):
        TaskRequest(
            objective="Investigate slow video uploads",
            repository_url="https://github.com/fastapi",
        )
