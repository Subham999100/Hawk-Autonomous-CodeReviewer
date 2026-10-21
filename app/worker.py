import asyncio
import logging
import signal

from app.core.config import settings
from app.db.session import init_db
from app.services.worker import run_worker_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [worker] %(name)s: %(message)s",
)
logger = logging.getLogger("hawk.worker_main")


async def main():
    logger.info("Initializing Hawk Worker...")
    await init_db()

    stop_event = asyncio.Event()

    def signal_handler():
        logger.info("Shutdown signal received. Stopping worker loop...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows does not support add_signal_handler for all signals
            pass

    logger.info("Hawk Worker listening for queued investigation tasks...")
    await run_worker_loop(stop_event)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Worker stopped by user.")
