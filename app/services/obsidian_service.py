import logging
from typing import Any, Dict, Optional
import httpx

from app.core.config import settings
from app.models.report import InvestigationReport

logger = logging.getLogger("hawk.obsidian")


def format_investigation_note(
    task_id: str,
    objective: str,
    repository_name: str,
    report: InvestigationReport,
    evidence_stats: Optional[Dict[str, Any]] = None,
) -> str:
    """Formats an investigation report into Obsidian-compatible Markdown with frontmatter."""
    safe_repo_tag = repository_name.replace("/", "-").lower()

    findings_md = ""
    for idx, f in enumerate(report.findings, start=1):
        findings_md += f"### {idx}. {f.title} ({f.confidence.value.upper()} Confidence)\n"
        findings_md += f"{f.explanation}\n\n"
        if f.evidence_paths:
            findings_md += "**Evidence Paths:**\n"
            for p in f.evidence_paths:
                findings_md += f"- `{p}`\n"
            findings_md += "\n"

    hypotheses_md = "\n".join(f"- {h}" for h in report.root_cause_hypotheses) or "- None identified"
    steps_md = "\n".join(f"- {s}" for s in report.recommended_next_steps) or "- None specified"
    limitations_md = "\n".join(f"- {l}" for l in report.limitations) or "- None reported"

    return f"""---
task_id: "{task_id}"
repository: "{repository_name}"
type: engineering_memory
source: hawk
tags:
  - hawk/investigation
  - repo/{safe_repo_tag}
---

# Investigation: {repository_name}

> **Objective:** {objective}

## Executive Summary
{report.summary}

## Key Findings
{findings_md if findings_md else "No specific findings recorded."}

## Root Cause Hypotheses
{hypotheses_md}

## Recommended Next Steps
{steps_md}

## Limitations
{limitations_md}

---
*Generated autonomously by Hawk Engineering Platform.*
"""


async def sync_investigation_memory(
    task_id: str,
    objective: str,
    repository_name: str,
    report: InvestigationReport,
    evidence_stats: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Syncs the investigation report to Obsidian using the Obsidian Local REST API (PUT /vault/{path}).
    """
    note_content = format_investigation_note(task_id, objective, repository_name, report, evidence_stats)
    safe_repo = repository_name.replace("/", "_")
    vault_path = f"{settings.obsidian_vault_subpath}/{safe_repo}_{task_id}.md".strip("/")

    api_key = settings.obsidian_api_key.strip() if settings.obsidian_api_key else ""
    base_url = settings.obsidian_api_url.rstrip("/")

    if not api_key:
        logger.info("OBSIDIAN_API_KEY is not configured; storing engineering memory note locally in task record.")
        return {
            "status": "local_memory_stored",
            "vault_path": vault_path,
            "note_length": len(note_content),
            "note_preview": note_content[:300],
            "synced_to_vault": False,
            "reason": "OBSIDIAN_API_KEY unconfigured",
        }

    url = f"{base_url}/vault/{vault_path}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "text/markdown",
    }

    try:
        # Note: Obsidian Local REST API usually runs HTTPS with self-signed certificate, verify=False allowed
        async with httpx.AsyncClient(timeout=8.0, verify=False) as client:
            response = await client.put(url, content=note_content.encode("utf-8"), headers=headers)

        if response.status_code in (200, 201, 204):
            logger.info("Successfully synced engineering memory note to Obsidian vault: %s", vault_path)
            return {
                "status": "synced",
                "vault_path": vault_path,
                "synced_to_vault": True,
                "status_code": response.status_code,
            }
        else:
            logger.warning(
                "Obsidian Local REST API returned status %d for %s. Storing note locally.",
                response.status_code,
                url,
            )
            return {
                "status": "sync_failed",
                "vault_path": vault_path,
                "synced_to_vault": False,
                "error": f"Obsidian API returned {response.status_code}",
                "note_preview": note_content[:300],
            }

    except Exception as exc:
        logger.warning("Unable to reach Obsidian Local REST API at %s: %s", base_url, str(exc))
        return {
            "status": "unreachable",
            "vault_path": vault_path,
            "synced_to_vault": False,
            "error": str(exc),
            "note_preview": note_content[:300],
        }
