
import httpx
import pytest
from app.services.github_client import get_repository_file
from app.services.github_client import (
    GitHubClientError,
    get_repository_metadata,
)


@pytest.mark.asyncio
async def test_returns_repository_metadata(monkeypatch):
    async def mock_get(self, url, **kwargs):
        return httpx.Response(
            200,
            json={
                "full_name": "fastapi/fastapi",
                "description": "FastAPI framework",
                "default_branch": "master",
                "html_url": "https://github.com/fastapi/fastapi",
                "private": False,
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    result = await get_repository_metadata("fastapi", "fastapi")

    assert result["full_name"] == "fastapi/fastapi"
    assert result["default_branch"] == "master"
    assert result["private"] is False


@pytest.mark.asyncio
async def test_handles_repository_not_found(monkeypatch):
    async def mock_get(self, url, **kwargs):
        return httpx.Response(
            404,
            json={"message": "Not Found"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    with pytest.raises(GitHubClientError, match="Repository not found"):
        await get_repository_metadata("unknown-owner", "unknown-repo")


@pytest.mark.asyncio
async def test_handles_timeout(monkeypatch):
    async def mock_get(self, url, **kwargs):
        raise httpx.TimeoutException("Request timed out")

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    with pytest.raises(GitHubClientError, match="timed out"):
        await get_repository_metadata("fastapi", "fastapi")

@pytest.mark.asyncio
async def test_rejects_parent_directory_path():
    with pytest.raises(GitHubClientError, match="Invalid repository file path"):
        await get_repository_file("fastapi", "fastapi", "../.env")


@pytest.mark.asyncio
async def test_rejects_disallowed_extension():
    with pytest.raises(GitHubClientError, match="File type is not allowed"):
        await get_repository_file("fastapi", "fastapi", "image.png")
