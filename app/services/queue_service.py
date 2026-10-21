import asyncio
import json
import logging
from typing import AsyncGenerator, Optional
import redis.asyncio as redis

from app.core.config import settings

logger = logging.getLogger("hawk.queue")

QUEUE_NAME = "hawk:queue:tasks"
CANCEL_PREFIX = "hawk:task:cancel:"
CHANNEL_PREFIX = "hawk:task:events:"

# Global fallback in-memory queue for environments without live Redis
_in_memory_queue: asyncio.Queue = asyncio.Queue()
_in_memory_subscribers: dict[str, list[asyncio.Queue]] = {}
_in_memory_cancellations: set[str] = set()

_redis_client: Optional[redis.Redis] = None
_redis_last_check_time: float = 0
_redis_failed: bool = False


async def get_redis_client() -> Optional[redis.Redis]:
    global _redis_client, _redis_last_check_time, _redis_failed
    import time

    if _redis_client is not None:
        return _redis_client

    now = time.time()
    if _redis_failed and (now - _redis_last_check_time < 30.0):
        return None

    _redis_last_check_time = now
    try:
        client = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_timeout=0.3,
            socket_connect_timeout=0.3,
        )
        await client.ping()
        _redis_client = client
        _redis_failed = False
        logger.info("Connected to Redis at %s", settings.redis_url)
        return _redis_client
    except Exception as exc:
        _redis_failed = True
        logger.debug(
            "Redis not reachable (%s). Using in-memory fallback queue and event broker.",
            str(exc),
        )
        return None


async def enqueue_task(task_id: str) -> bool:
    """Enqueues a task ID to Redis, falling back to in-memory queue."""
    client = await get_redis_client()
    if client:
        try:
            await client.lpush(QUEUE_NAME, task_id)
            return True
        except Exception as exc:
            logger.error("Failed to enqueue task to Redis (%s), falling back to in-memory", exc)

    await _in_memory_queue.put(task_id)
    return True


async def dequeue_task(timeout: int = 2) -> Optional[str]:
    """Dequeues a task ID from Redis or in-memory queue."""
    client = await get_redis_client()
    if client:
        try:
            item = await client.brpop(QUEUE_NAME, timeout=timeout)
            if item:
                return item[1]
        except Exception as exc:
            logger.error("Failed to dequeue from Redis (%s)", exc)

    try:
        return await asyncio.wait_for(_in_memory_queue.get(), timeout=float(timeout))
    except (asyncio.TimeoutError, TimeoutError):
        return None


async def request_task_cancellation(task_id: str) -> None:
    """Sets a cancellation flag in Redis and in-memory set."""
    _in_memory_cancellations.add(task_id)
    client = await get_redis_client()
    if client:
        try:
            await client.set(f"{CANCEL_PREFIX}{task_id}", "1", ex=3600)
        except Exception as exc:
            logger.warning("Failed to set cancellation in Redis: %s", exc)


async def is_task_cancelled(task_id: str) -> bool:
    """Checks if a cancellation was requested for task_id."""
    if task_id in _in_memory_cancellations:
        return True

    client = await get_redis_client()
    if client:
        try:
            val = await client.get(f"{CANCEL_PREFIX}{task_id}")
            return val is not None
        except Exception:
            pass
    return False


async def publish_task_event(task_id: str, event_type: str, payload: dict) -> None:
    """Publishes a live event for SSE subscribers via Redis channel or in-memory queues."""
    event_data = {
        "task_id": task_id,
        "event_type": event_type,
        "payload": payload,
    }
    encoded = json.dumps(event_data)

    # In-memory distribution
    if task_id in _in_memory_subscribers:
        for q in list(_in_memory_subscribers[task_id]):
            try:
                q.put_nowait(event_data)
            except Exception:
                pass

    # Redis distribution
    client = await get_redis_client()
    if client:
        try:
            await client.publish(f"{CHANNEL_PREFIX}{task_id}", encoded)
        except Exception as exc:
            logger.debug("Failed to publish event to Redis: %s", exc)


async def subscribe_task_events(task_id: str) -> AsyncGenerator[dict, None]:
    """Yields live task events for SSE streaming."""
    client = await get_redis_client()
    queue = asyncio.Queue()

    if task_id not in _in_memory_subscribers:
        _in_memory_subscribers[task_id] = []
    _in_memory_subscribers[task_id].append(queue)

    pubsub = None
    if client:
        try:
            pubsub = client.pubsub()
            await pubsub.subscribe(f"{CHANNEL_PREFIX}{task_id}")
        except Exception as exc:
            logger.debug("Failed to subscribe via Redis: %s", exc)
            pubsub = None

    try:
        while True:
            # Check Redis pubsub if available
            if pubsub:
                try:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
                    if message and message.get("type") == "message":
                        data = json.loads(message["data"])
                        yield data
                except Exception:
                    pass

            # Check in-memory queue
            try:
                item = await asyncio.wait_for(queue.get(), timeout=0.5)
                yield item
            except (asyncio.TimeoutError, TimeoutError):
                pass

            # Yield control
            await asyncio.sleep(0.1)

    finally:
        if task_id in _in_memory_subscribers and queue in _in_memory_subscribers[task_id]:
            _in_memory_subscribers[task_id].remove(queue)
            if not _in_memory_subscribers[task_id]:
                del _in_memory_subscribers[task_id]
        if pubsub:
            try:
                await pubsub.unsubscribe(f"{CHANNEL_PREFIX}{task_id}")
                await pubsub.close()
            except Exception:
                pass
