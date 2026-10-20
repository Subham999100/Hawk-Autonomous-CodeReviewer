
import httpx
import base64


GITHUB_API_BASE = "https://api.github.com"


class GitHubClientError(Exception):
    """Raised when GitHub API access fails."""


async def get_repository_metadata(owner: str, repo: str) -> dict:
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )

    except httpx.TimeoutException as exc:
        raise GitHubClientError(
            "GitHub API request timed out"
        ) from exc

    except httpx.RequestError as exc:
        raise GitHubClientError(
            "Unable to connect to GitHub"
        ) from exc

    if response.status_code == 404:
        raise GitHubClientError(
            "Repository not found or not publicly accessible"
        )

    if response.status_code == 403:
        raise GitHubClientError(
            "GitHub access forbidden or API rate limit exceeded"
        )

    if response.status_code != 200:
        raise GitHubClientError(
            f"GitHub API returned status {response.status_code}"
        )

    data = response.json()

    return {
        "full_name": data["full_name"],
        "description": data["description"],
        "default_branch": data["default_branch"],
        "html_url": data["html_url"],
        "private": data["private"],
    }

ALLOWED_SOURCE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".go",
    ".rs",
    ".sql",
    ".html",
    ".css",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".md",
}

MAX_FILE_SIZE = 100_000


async def get_repository_file(
    owner: str,
    repo: str,
    path: str,
) -> dict:
    from pathlib import PurePosixPath

    file_path = PurePosixPath(path)

    if file_path.is_absolute() or ".." in file_path.parts:
        raise GitHubClientError("Invalid repository file path")

    if file_path.suffix.lower() not in ALLOWED_SOURCE_EXTENSIONS:
        raise GitHubClientError("File type is not allowed")

    if file_path.name.lower() in {
        ".env",
        ".env.local",
        "id_rsa",
        "id_ed25519",
        "credentials",
        "secrets.yaml",
        "secrets.yml",
    }:
        raise GitHubClientError("Sensitive file access is blocked")

    url = (
        f"{GITHUB_API_BASE}/repos/{owner}/{repo}"
        f"/contents/{path}"
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
    except httpx.TimeoutException as exc:
        raise GitHubClientError(
            "GitHub API request timed out"
        ) from exc
    except httpx.RequestError as exc:
        raise GitHubClientError(
            "Unable to connect to GitHub"
        ) from exc

    if response.status_code != 200:
        raise GitHubClientError(
            f"GitHub API returned status {response.status_code}"
        )

    data = response.json()

    if data.get("type") != "file":
        raise GitHubClientError("Path does not identify a file")

    size = data.get("size")

    if not isinstance(size, int) or size < 0 or size > MAX_FILE_SIZE:
        raise GitHubClientError("File size is invalid or exceeds the limit")

    if data.get("encoding") != "base64":
        raise GitHubClientError("Unsupported file encoding")

    try:
        content_bytes = base64.b64decode(
            data["content"],
            validate=True,
        )
        content = content_bytes.decode("utf-8")
    except (KeyError, ValueError, UnicodeDecodeError) as exc:
        raise GitHubClientError(
            "Unable to decode repository file"
        ) from exc

    if len(content_bytes) > MAX_FILE_SIZE:
        raise GitHubClientError("File exceeds the size limit")

    return {
        "path": data["path"],
        "size": len(content_bytes),
        "content": content,
    }


async def get_repository_tree(
    owner: str,
    repo: str,
    branch: str,
) -> list[dict]:
    from urllib.parse import quote

    safe_branch = quote(branch, safe="")
    url = (
        f"{GITHUB_API_BASE}/repos/{owner}/{repo}"
        f"/git/trees/{safe_branch}"
    )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                url,
                params={"recursive": "1"},
                headers={
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )

    except httpx.TimeoutException as exc:
        raise GitHubClientError(
            "GitHub repository tree request timed out"
        ) from exc

    except httpx.RequestError as exc:
        raise GitHubClientError(
            "Unable to retrieve the GitHub repository tree"
        ) from exc

    if response.status_code == 404:
        raise GitHubClientError(
            "Repository branch or repository was not found"
        )

    if response.status_code == 403:
        raise GitHubClientError(
            "GitHub access forbidden or API rate limit exceeded"
        )

    if response.status_code != 200:
        raise GitHubClientError(
            f"GitHub tree API returned status {response.status_code}"
        )

    data = response.json()
    tree = data.get("tree")

    if not isinstance(tree, list):
        raise GitHubClientError(
            "GitHub returned an invalid repository tree"
        )

    if data.get("truncated", False):
        raise GitHubClientError(
            "GitHub returned an incomplete repository tree. "
            "A non-recursive tree traversal is required."
        )

    source_files = []

    for item in tree:
        if item.get("type") != "blob":
            continue

        path = item.get("path")

        if not isinstance(path, str):
            continue

        source_files.append({
            "path": path,
            "size": item.get("size"),
        })

    return source_files


IGNORED_DIRECTORIES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    "coverage",
    ".next",
    ".pytest_cache",
}

SENSITIVE_FILE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "id_rsa",
    "id_ed25519",
    "credentials",
    "secrets.yaml",
    "secrets.yml",
}

MAX_SELECTED_FILES = 30


def select_repository_files(
    tree: list[dict],
) -> list[dict]:
    from pathlib import PurePosixPath

    selected = []

    for item in tree:
        path = item.get("path")
        size = item.get("size")

        if not isinstance(path, str):
            continue

        file_path = PurePosixPath(path)
        parts = {part.lower() for part in file_path.parts}

        if parts.intersection(IGNORED_DIRECTORIES):
            continue

        if file_path.name.lower() in SENSITIVE_FILE_NAMES:
            continue

        if file_path.suffix.lower() not in ALLOWED_SOURCE_EXTENSIONS:
            continue

        if not isinstance(size, int) or size < 0:
            continue

        if size > MAX_FILE_SIZE:
            continue

        selected.append({
            "path": path,
            "size": size,
        })

    selected.sort(
        key=lambda item: (
            0 if item["path"].lower().split("/")[-1] in {
                "main.py",
                "app.py",
                "server.py",
                "index.js",
                "index.ts",
                "package.json",
                "pyproject.toml",
            } else 1,
            item["path"].count("/"),
            item["path"].lower(),
        )
    )

    return selected[:MAX_SELECTED_FILES]

