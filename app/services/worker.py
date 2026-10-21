import asyncio
from datetime import datetime, timezone
import logging
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.models import TaskRecord, ReportRecord, TaskEventRecord, utcnow
from app.db.session import AsyncSessionLocal
from app.models.report import InvestigationReport
from app.models.task import TaskStatus
from app.services.github_client import GitHubClientError
from app.services.jev_service import orchestrate_investigation_triage
from app.services.obsidian_service import sync_investigation_memory
from app.services.queue_service import (
    dequeue_task,
    enqueue_task,
    is_task_cancelled,
    publish_task_event,
)
from app.services.reasoning_service import analyze_engineering_evidence
from app.services.repository_evidence import collect_repository_evidence

logger = logging.getLogger("hawk.worker")


async def record_event(
    session,
    task_id: str,
    event_type: str,
    payload: dict,
) -> TaskEventRecord:
    """Persists an event to the task_events table and publishes it to live subscribers."""
    event = TaskEventRecord(
        task_id=task_id,
        event_type=event_type,
        payload=payload,
        created_at=utcnow(),
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)

    # Publish to live SSE subscribers
    await publish_task_event(
        task_id=task_id,
        event_type=event_type,
        payload={"id": event.id, "created_at": event.created_at.isoformat(), **payload},
    )
    return event


def sanitize_error(err_str: str) -> str:
    """Removes sensitive patterns or raw paths from error messages."""
    cleaned = err_str.replace(".env", "[config]")
    if "sk-" in cleaned:
        # Mask api key patterns
        import re
        cleaned = re.sub(r"sk-[a-zA-Z0-9_-]{8,}", "sk-***REDACTED***", cleaned)
    return cleaned


async def process_task(task_id: str) -> bool:
    """
    Executes a bounded, multi-phase investigation task with cancellation checks,
    Jev System One orchestration, GitHub evidence collection, OpenAI reasoning,
    and Obsidian memory synchronization.
    """
    logger.info("Starting processing for task %s", task_id)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(TaskRecord).where(TaskRecord.id == task_id).options(selectinload(TaskRecord.report))
        )
        task = result.scalar_one_or_none()
        if not task:
            logger.error("Task %s not found in database", task_id)
            return False

        if await is_task_cancelled(task_id):
            task.status = TaskStatus.BLOCKED.value
            task.error_message = "Task was cancelled before execution started."
            await session.commit()
            await record_event(session, task_id, "status_change", {"status": "cancelled"})
            return False

        try:
            # Phase 1: Planning & Jev System One Orchestration
            task.status = TaskStatus.PLANNING.value
            task.started_at = utcnow()
            await session.commit()
            await record_event(session, task_id, "status_change", {"status": task.status})

            # Parse owner and repo from repository URL
            from urllib.parse import urlparse
            parsed_url = urlparse(task.repository_url)
            path_parts = parsed_url.path.strip("/").split("/")
            if len(path_parts) != 2:
                raise ValueError("Repository URL must contain owner and repository name")
            owner, repo = path_parts
            if repo.endswith(".git"):
                repo = repo[:-4]

            if await is_task_cancelled(task_id):
                raise asyncio.CancelledError("Task cancelled by user during planning")

            # Call Jev System One decision service
            jev_decision = await orchestrate_investigation_triage(
                objective=task.objective,
                repository_name=f"{owner}/{repo}",
                tree_sample=[],
            )
            task.orchestration_decision = jev_decision
            await session.commit()
            await record_event(
                session,
                task_id,
                "jev_triage",
                {"orchestration_decision": jev_decision},
            )

            if await is_task_cancelled(task_id):
                raise asyncio.CancelledError("Task cancelled by user before evidence collection")

            # Phase 2: Executing - Evidence Collection
            task.status = TaskStatus.EXECUTING.value
            await session.commit()
            await record_event(session, task_id, "status_change", {"status": task.status})

            evidence_package = await collect_repository_evidence(owner, repo)
            evidence_stats = {
                "files_discovered": evidence_package["files_discovered"],
                "files_selected": evidence_package["files_selected"],
                "files_retrieved": evidence_package["files_retrieved"],
                "total_evidence_bytes": evidence_package["total_evidence_bytes"],
            }
            task.evidence_stats = evidence_stats
            task.repository_metadata = evidence_package["repository"]
            await session.commit()

            await record_event(
                session,
                task_id,
                "evidence_collected",
                {
                    "stats": evidence_stats,
                    "repository": evidence_package["repository"],
                },
            )

            if await is_task_cancelled(task_id):
                raise asyncio.CancelledError("Task cancelled by user after evidence collection")

            # Check for blocked state (empty evidence)
            if not evidence_package["evidence"]:
                task.status = TaskStatus.BLOCKED.value
                task.completed_at = utcnow()
                blocked_report = InvestigationReport(
                    summary=(
                        "Investigation blocked: no eligible source-file evidence "
                        "could be collected from the repository."
                    ),
                    findings=[],
                    root_cause_hypotheses=[],
                    recommended_next_steps=[
                        "Ensure the repository contains supported source files within size limits."
                    ],
                    limitations=[
                        "No eligible source-file evidence was available in the repository."
                    ],
                )
                report_record = ReportRecord(
                    task_id=task.id,
                    summary=blocked_report.summary,
                    findings=[f.model_dump() for f in blocked_report.findings],
                    root_cause_hypotheses=blocked_report.root_cause_hypotheses,
                    recommended_next_steps=blocked_report.recommended_next_steps,
                    limitations=blocked_report.limitations,
                )
                session.add(report_record)
                await session.commit()

                await record_event(
                    session,
                    task_id,
                    "status_change",
                    {"status": task.status, "summary": blocked_report.summary},
                )
                return True

            # Phase 3: Verifying - AI Reasoning via OpenAI
            task.status = TaskStatus.VERIFYING.value
            await session.commit()
            await record_event(session, task_id, "status_change", {"status": task.status})

            repo_full_name = evidence_package["repository"].get("full_name", f"{owner}/{repo}")
            report = await analyze_engineering_evidence(
                objective=task.objective,
                repository_name=repo_full_name,
                evidence=evidence_package["evidence"],
            )

            report_record = ReportRecord(
                task_id=task.id,
                summary=report.summary,
                findings=[f.model_dump() for f in report.findings],
                root_cause_hypotheses=report.root_cause_hypotheses,
                recommended_next_steps=report.recommended_next_steps,
                limitations=report.limitations,
            )
            session.add(report_record)
            await session.commit()

            await record_event(
                session,
                task_id,
                "report_generated",
                {"summary": report.summary, "findings_count": len(report.findings)},
            )

            # Phase 4: Engineering Memory Sync (Obsidian Local REST API)
            obsidian_res = await sync_investigation_memory(
                task_id=task.id,
                objective=task.objective,
                repository_name=repo_full_name,
                report=report,
                evidence_stats=evidence_stats,
            )
            task.memory_sync_status = obsidian_res
            task.status = TaskStatus.COMPLETED.value
            task.completed_at = utcnow()
            await session.commit()

            await record_event(
                session,
                task_id,
                "obsidian_synced",
                {"obsidian": obsidian_res},
            )
            await record_event(
                session,
                task_id,
                "status_change",
                {"status": task.status},
            )

            logger.info("Task %s completed successfully", task_id)
            return True

        except asyncio.CancelledError:
            task.status = TaskStatus.BLOCKED.value
            task.error_message = "Investigation cancelled by user."
            task.completed_at = utcnow()
            await session.commit()
            await record_event(session, task_id, "status_change", {"status": "cancelled"})
            logger.info("Task %s cancelled", task_id)
            return False

        except Exception as exc:
            logger.exception("Error executing task %s: %s", task_id, exc)
            task.retry_count += 1
            sanitized = sanitize_error(str(exc))

            if task.retry_count < settings.max_retries and not isinstance(exc, (ValueError, GitHubClientError)):
                logger.info("Re-enqueuing task %s (retry %d/%d)", task_id, task.retry_count, settings.max_retries)
                task.status = TaskStatus.RECEIVED.value
                task.error_message = f"Transient failure, retrying: {sanitized}"
                await session.commit()
                await record_event(session, task_id, "retry", {"retry_count": task.retry_count, "error": sanitized})
                await enqueue_task(task_id)
                return False

            task.status = TaskStatus.FAILED.value
            task.error_message = sanitized
            task.completed_at = utcnow()
            await session.commit()
            await record_event(session, task_id, "status_change", {"status": task.status, "error": sanitized})
            return False


async def run_worker_loop(stop_event: Optional[asyncio.Event] = None):
    """Continuous worker loop polling tasks from the queue."""
    logger.info("Hawk background worker process started.")
    while stop_event is None or not stop_event.is_set():
        try:
            task_id = await dequeue_task(timeout=2)
            if task_id:
                try:
                    await asyncio.wait_for(
                        process_task(task_id),
                        timeout=float(settings.task_timeout_seconds),
                    )
                except asyncio.TimeoutError:
                    logger.error("Task %s exceeded timeout of %d seconds", task_id, settings.task_timeout_seconds)
                    async with AsyncSessionLocal() as session:
                        result = await session.execute(select(TaskRecord).where(TaskRecord.id == task_id))
                        task = result.scalar_one_or_none()
                        if task:
                            task.status = TaskStatus.FAILED.value
                            task.error_message = f"Execution exceeded maximum timeout of {settings.task_timeout_seconds} seconds."
                            task.completed_at = utcnow()
                            await session.commit()
                            await record_event(
                                session,
                                task_id,
                                "status_change",
                                {"status": task.status, "error": task.error_message},
                            )
        except Exception as exc:
            logger.error("Error in worker polling loop: %s", exc)
            await asyncio.sleep(1.0)
