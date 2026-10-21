import asyncio
import json
import logging
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.models import TaskRecord, TaskEventRecord, User
from app.db.session import get_db
from app.services.queue_service import subscribe_task_events

logger = logging.getLogger("hawk.sse")
router = APIRouter()


@router.get("/tasks/{task_id}/events")
@router.get("/tasks/{task_id}/stream")
async def stream_task_events(
    task_id: str,
    last_event_id: Optional[int] = Header(None, alias="Last-Event-ID"),
    last_event_id_query: Optional[int] = Query(None, alias="last_event_id"),
    token: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Streams Server-Sent Events (SSE) for task progress with reconnect and replay support.
    Accepts authentication via Authorization header or query parameter 'token' for EventSource compatibility.
    """
    # Verify task existence and authorization
    result = await db.execute(select(TaskRecord).where(TaskRecord.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if current_user.role != "admin" and task.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this task stream")

    replay_after_id = last_event_id or last_event_id_query or 0

    async def event_generator():
        # 1. Replay historical events from database starting after replay_after_id
        from app.db.session import AsyncSessionLocal
        highest_id = replay_after_id
        is_terminal = False

        async with AsyncSessionLocal() as session:
            events_result = await session.execute(
                select(TaskEventRecord)
                .where(TaskEventRecord.task_id == task_id)
                .where(TaskEventRecord.id > replay_after_id)
                .order_by(TaskEventRecord.id.asc())
            )
            historical_events = events_result.scalars().all()
            for ev in historical_events:
                highest_id = max(highest_id, ev.id)
                payload_str = json.dumps(ev.payload)
                yield f"id: {ev.id}\nevent: {ev.event_type}\ndata: {payload_str}\n\n"
                if ev.event_type == "status_change":
                    st = ev.payload.get("status")
                    if st in ("completed", "failed", "blocked", "cancelled"):
                        is_terminal = True

        if is_terminal:
            yield f"event: close\ndata: {json.dumps({'message': 'Task reached terminal state'})}\n\n"
            return

        # 2. Subscribe to live events from queue
        try:
            async for live_event in subscribe_task_events(task_id):
                ev_type = live_event.get("event_type", "message")
                payload = live_event.get("payload", {})
                ev_id = payload.get("id") or highest_id + 1
                highest_id = max(highest_id, ev_id)

                yield f"id: {ev_id}\nevent: {ev_type}\ndata: {json.dumps(payload)}\n\n"

                if ev_type == "status_change":
                    st = payload.get("status")
                    if st in ("completed", "failed", "blocked", "cancelled"):
                        yield f"event: close\ndata: {json.dumps({'message': 'Task completed'})}\n\n"
                        break
        except asyncio.CancelledError:
            logger.info("SSE client disconnected from task %s stream", task_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
