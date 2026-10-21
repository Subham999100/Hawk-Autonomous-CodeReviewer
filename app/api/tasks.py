import asyncio
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_user
from app.db.models import TaskRecord, ReportRecord, User, utcnow
from app.db.session import get_db
from app.models.report import InvestigationReport
from app.models.task import TaskRequest, TaskStatus
from app.services.github_client import GitHubClientError
from app.services.queue_service import enqueue_task, request_task_cancellation
from app.services.reasoning_service import analyze_engineering_evidence
from app.services.repository_evidence import collect_repository_evidence
from app.services.worker import process_task, record_event
from openai import AuthenticationError, OpenAIError

logger = logging.getLogger("hawk.api.tasks")
router = APIRouter(prefix="/tasks", tags=["Tasks"])


class TaskSummaryResponse(BaseModel):
    id: str
    objective: str
    repository_url: str
    status: str
    created_at: str
    updated_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    evidence_stats: Optional[dict] = None
    orchestration_decision: Optional[dict] = None
    memory_sync_status: Optional[dict] = None
    error_message: Optional[str] = None


class TaskSubmissionResponse(BaseModel):
    task_id: str
    status: str
    objective: str
    repository_url: str
    created_at: str


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        202: {"description": "Task accepted for asynchronous processing", "model": TaskSubmissionResponse},
        200: {"description": "Synchronous task execution (when sync=true)"},
    },
)
async def create_task(
    task_req: TaskRequest,
    sync: bool = Query(False, description="Run synchronously for testing/direct evaluation"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    response: Response = None,
):
    """
    Submits an engineering investigation task.
    By default, returns HTTP 202 Accepted with a persistent task ID for background processing.
    """
    # Validate repository URL path
    repository_path = task_req.repository_url.path.strip("/").split("/")
    if len(repository_path) != 2:
        raise HTTPException(
            status_code=400,
            detail="Repository URL must contain an owner and repository name",
        )

    owner, repo = repository_path
    if repo.endswith(".git"):
        repo = repo[:-4]

    if not owner or not repo:
        raise HTTPException(
            status_code=400,
            detail="Invalid repository owner or repository name",
        )

    # Persist task in database with status 'received'
    new_task = TaskRecord(
        user_id=current_user.id,
        objective=task_req.objective,
        repository_url=str(task_req.repository_url),
        status=TaskStatus.RECEIVED.value,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(new_task)
    await db.commit()
    await db.refresh(new_task)

    await record_event(
        db,
        new_task.id,
        "status_change",
        {"status": new_task.status, "objective": new_task.objective},
    )

    # Synchronous evaluation mode (used by unit tests or direct evaluation)
    if sync:
        try:
            evidence_package = await collect_repository_evidence(owner, repo)
        except GitHubClientError as exc:
            new_task.status = TaskStatus.FAILED.value
            new_task.error_message = str(exc)
            await db.commit()
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        evidence_stats = {
            "files_discovered": evidence_package["files_discovered"],
            "files_selected": evidence_package["files_selected"],
            "files_retrieved": evidence_package["files_retrieved"],
            "total_evidence_bytes": evidence_package["total_evidence_bytes"],
        }
        new_task.evidence_stats = evidence_stats
        new_task.repository_metadata = evidence_package["repository"]

        if not evidence_package["evidence"]:
            new_task.status = TaskStatus.BLOCKED.value
            new_task.completed_at = utcnow()
            report = InvestigationReport(
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
            report_rec = ReportRecord(
                task_id=new_task.id,
                summary=report.summary,
                findings=[],
                root_cause_hypotheses=[],
                recommended_next_steps=report.recommended_next_steps,
                limitations=report.limitations,
            )
            db.add(report_rec)
            await db.commit()
            if response:
                response.status_code = status.HTTP_200_OK
            return {
                "task_id": new_task.id,
                "status": TaskStatus.BLOCKED.value,
                "objective": new_task.objective,
                "repository": evidence_package["repository"],
                "evidence_stats": evidence_stats,
                "report": report,
            }

        repo_full_name = evidence_package["repository"].get("full_name", f"{owner}/{repo}")

        try:
            report = await analyze_engineering_evidence(
                objective=new_task.objective,
                repository_name=repo_full_name,
                evidence=evidence_package["evidence"],
            )
        except RuntimeError as exc:
            error_msg = str(exc)
            new_task.status = TaskStatus.FAILED.value
            new_task.error_message = error_msg
            await db.commit()
            if "API key is missing" in error_msg or "OPENAI_API_KEY" in error_msg:
                raise HTTPException(
                    status_code=500,
                    detail="OpenAI API key is missing or unconfigured",
                ) from exc
            raise HTTPException(
                status_code=502,
                detail="Reasoning service failed to return a valid report",
            ) from exc
        except AuthenticationError as exc:
            new_task.status = TaskStatus.FAILED.value
            new_task.error_message = "Reasoning service authentication failed"
            await db.commit()
            raise HTTPException(
                status_code=500,
                detail="Reasoning service authentication failed",
            ) from exc
        except OpenAIError as exc:
            new_task.status = TaskStatus.FAILED.value
            new_task.error_message = "Reasoning service request failed"
            await db.commit()
            raise HTTPException(
                status_code=502,
                detail="Reasoning service request failed",
            ) from exc

        report_rec = ReportRecord(
            task_id=new_task.id,
            summary=report.summary,
            findings=[f.model_dump() for f in report.findings],
            root_cause_hypotheses=report.root_cause_hypotheses,
            recommended_next_steps=report.recommended_next_steps,
            limitations=report.limitations,
        )
        db.add(report_rec)
        new_task.status = TaskStatus.COMPLETED.value
        new_task.completed_at = utcnow()
        await db.commit()

        if response:
            response.status_code = status.HTTP_200_OK
        return {
            "task_id": new_task.id,
            "status": TaskStatus.COMPLETED.value,
            "objective": new_task.objective,
            "repository": evidence_package["repository"],
            "evidence_stats": evidence_stats,
            "report": report,
        }

    # Asynchronous background execution: Enqueue task ID
    await enqueue_task(new_task.id)

    # Trigger background worker runner task in-process if standalone
    asyncio.create_task(process_task(new_task.id))

    return {
        "task_id": new_task.id,
        "status": new_task.status,
        "objective": new_task.objective,
        "repository_url": new_task.repository_url,
        "created_at": new_task.created_at.isoformat(),
    }


@router.get("", response_model=List[TaskSummaryResponse])
async def list_tasks(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Lists tasks owned by the authenticated user (or all if admin)."""
    query = select(TaskRecord)
    if current_user.role != "admin":
        query = query.where(TaskRecord.user_id == current_user.id)

    if status_filter:
        query = query.where(TaskRecord.status == status_filter)

    query = query.order_by(desc(TaskRecord.created_at)).offset(offset).limit(limit)
    result = await db.execute(query)
    tasks = result.scalars().all()

    return [
        {
            "id": t.id,
            "objective": t.objective,
            "repository_url": t.repository_url,
            "status": t.status,
            "created_at": t.created_at.isoformat(),
            "updated_at": t.updated_at.isoformat(),
            "started_at": t.started_at.isoformat() if t.started_at else None,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            "evidence_stats": t.evidence_stats,
            "orchestration_decision": t.orchestration_decision,
            "memory_sync_status": t.memory_sync_status,
            "error_message": t.error_message,
        }
        for t in tasks
    ]


@router.get("/{task_id}")
async def get_task_details(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieves full metadata, status, and execution stats for a specific task."""
    result = await db.execute(
        select(TaskRecord).where(TaskRecord.id == task_id).options(selectinload(TaskRecord.report))
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if current_user.role != "admin" and task.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this task")

    return {
        "id": task.id,
        "user_id": task.user_id,
        "objective": task.objective,
        "repository_url": task.repository_url,
        "status": task.status,
        "repository_metadata": task.repository_metadata,
        "evidence_stats": task.evidence_stats,
        "orchestration_decision": task.orchestration_decision,
        "memory_sync_status": task.memory_sync_status,
        "retry_count": task.retry_count,
        "error_message": task.error_message,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "has_report": task.report is not None,
    }


@router.get("/{task_id}/report")
async def get_task_report(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieves the final structured investigation report for a completed task."""
    result = await db.execute(
        select(TaskRecord).where(TaskRecord.id == task_id).options(selectinload(TaskRecord.report))
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if current_user.role != "admin" and task.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this report")

    if not task.report:
        if task.status in (TaskStatus.FAILED.value, TaskStatus.BLOCKED.value):
            raise HTTPException(
                status_code=404,
                detail=f"Task did not produce a report (status: {task.status}). Error: {task.error_message}",
            )
        raise HTTPException(
            status_code=409,
            detail=f"Task is currently in status '{task.status}'; report is not yet ready",
        )

    return {
        "task_id": task.id,
        "objective": task.objective,
        "repository": task.repository_metadata,
        "evidence_stats": task.evidence_stats,
        "summary": task.report.summary,
        "findings": task.report.findings,
        "root_cause_hypotheses": task.report.root_cause_hypotheses,
        "recommended_next_steps": task.report.recommended_next_steps,
        "limitations": task.report.limitations,
        "created_at": task.report.created_at.isoformat(),
        "orchestration_decision": task.orchestration_decision,
        "memory_sync_status": task.memory_sync_status,
    }


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Requests cancellation of an ongoing task."""
    result = await db.execute(select(TaskRecord).where(TaskRecord.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if current_user.role != "admin" and task.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to cancel this task")

    if task.status in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.BLOCKED.value):
        raise HTTPException(
            status_code=400,
            detail=f"Task is already in terminal state '{task.status}' and cannot be cancelled",
        )

    await request_task_cancellation(task_id)
    task.status = TaskStatus.BLOCKED.value
    task.error_message = "Task cancelled by user request"
    task.completed_at = utcnow()
    await db.commit()

    await record_event(db, task_id, "status_change", {"status": "cancelled"})

    return {
        "task_id": task_id,
        "status": "cancelled",
        "message": "Cancellation request acknowledged",
    }
