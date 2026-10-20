
from app.services.github_client import (
    GitHubClientError,
    get_repository_metadata,
    get_repository_tree,
    get_repository_file,
    select_repository_files,
)

MAX_TOTAL_EVIDENCE_BYTES = 300_000


async def collect_repository_evidence(
    owner: str,
    repo: str,
) -> dict:
    repository = await get_repository_metadata(owner, repo)

    tree = await get_repository_tree(
        owner,
        repo,
        repository["default_branch"],
    )

    selected_files = select_repository_files(tree)

    evidence = []
    total_bytes = 0

    for item in selected_files:
        expected_size = item["size"]

        if total_bytes + expected_size > MAX_TOTAL_EVIDENCE_BYTES:
            continue

        try:
            file_data = await get_repository_file(
                owner,
                repo,
                item["path"],
            )
        except GitHubClientError:
            # Skip files that cannot be safely retrieved.
            continue

        actual_size = file_data["size"]

        if total_bytes + actual_size > MAX_TOTAL_EVIDENCE_BYTES:
            continue

        evidence.append(file_data)
        total_bytes += actual_size

    return {
        "repository": repository,
        "files_discovered": len(tree),
        "files_selected": len(selected_files),
        "files_retrieved": len(evidence),
        "total_evidence_bytes": total_bytes,
        "evidence": evidence,
    }
