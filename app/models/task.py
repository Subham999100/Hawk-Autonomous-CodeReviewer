
from enum import Enum

from pydantic import BaseModel, Field, HttpUrl, field_validator


class TaskStatus(str, Enum):
    RECEIVED = "received"
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class TaskRequest(BaseModel):
    objective: str = Field(min_length=10, max_length=2000)
    repository_url: HttpUrl

    @field_validator("repository_url")
    @classmethod
    def validate_github_url(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https":
            raise ValueError("Repository URL must use HTTPS")

        if value.host != "github.com":
            raise ValueError("Only github.com repository URLs are supported")

        if len(value.path.strip("/").split("/")) != 2:
            raise ValueError(
                "Repository URL must contain an owner and repository name"
            )

        return value
