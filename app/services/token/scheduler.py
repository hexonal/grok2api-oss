"""Token 刷新与过期清理调度器"""

import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from app.core.logger import logger
from app.core.storage import RedisStorage, StorageError, get_storage
from app.services.token.manager import get_token_manager


class TokenRefreshScheduler:
    """Token 自动刷新与过期清理调度器"""

    def __init__(
        self,
        refresh_interval_hours: int = 8,
        cleanup_interval_minutes: int = 10,
    ):
        self.refresh_interval_hours = refresh_interval_hours
        self.refresh_interval_seconds = refresh_interval_hours * 3600
        self.cleanup_interval_minutes = cleanup_interval_minutes
        self.cleanup_interval_seconds = cleanup_interval_minutes * 60
        self._refresh_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

    @asynccontextmanager
    async def _acquire_lock(self, name: str, ttl_seconds: int):
        storage = get_storage()
        lock_acquired = False
        redis_lock = None

        if isinstance(storage, RedisStorage):
            lock_key = f"grok2api:lock:{name}"
            redis_lock = storage.redis.lock(
                lock_key,
                timeout=max(ttl_seconds, 60),
                blocking_timeout=0,
            )
            lock_acquired = await redis_lock.acquire(blocking=False)
        else:
            try:
                async with storage.acquire_lock(name, timeout=0):
                    yield True
                    return
            except StorageError:
                yield False
                return

        try:
            yield lock_acquired
        finally:
            if redis_lock is not None and lock_acquired:
                try:
                    await redis_lock.release()
                except Exception:
                    pass

    async def _run_refresh_cycle(self):
        async with self._acquire_lock(
            "token_refresh",
            self.refresh_interval_seconds + 60,
        ) as lock_acquired:
            if not lock_acquired:
                logger.info("Scheduler: refresh skipped (lock not acquired)")
                return

            logger.info("Scheduler: starting token refresh...")
            manager = await get_token_manager()
            result = await manager.refresh_cooling_tokens()
            logger.info(
                "Scheduler: refresh completed - "
                f"checked={result['checked']}, "
                f"refreshed={result['refreshed']}, "
                f"recovered={result['recovered']}, "
                f"expired={result['expired']}"
            )

    async def _run_cleanup_cycle(self):
        async with self._acquire_lock(
            "token_expired_cleanup",
            self.cleanup_interval_seconds + 60,
        ) as lock_acquired:
            if not lock_acquired:
                logger.info("Scheduler: cleanup skipped (lock not acquired)")
                return

            logger.info("Scheduler: starting expired token cleanup...")
            manager = await get_token_manager()
            result = await manager.cleanup_expired_tokens()
            logger.info(
                "Scheduler: cleanup completed - "
                f"checked={result['checked']}, removed={result['removed']}"
            )

    async def _refresh_loop(self):
        logger.info(
            f"Scheduler: refresh loop started (interval: {self.refresh_interval_hours}h)"
        )
        while self._running:
            try:
                await asyncio.sleep(self.refresh_interval_seconds)
                await self._run_refresh_cycle()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scheduler: refresh error - {e}")

    async def _cleanup_loop(self):
        logger.info(
            "Scheduler: cleanup loop started "
            f"(interval: {self.cleanup_interval_minutes}m)"
        )
        while self._running:
            try:
                await asyncio.sleep(self.cleanup_interval_seconds)
                await self._run_cleanup_cycle()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scheduler: cleanup error - {e}")

    def start(self, enable_refresh: bool = True, enable_cleanup: bool = True):
        """启动调度器"""
        if self._running:
            logger.warning("Scheduler: already running")
            return

        self._running = True
        if enable_refresh:
            self._refresh_task = asyncio.create_task(self._refresh_loop())
        if enable_cleanup:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Scheduler: enabled")

    def stop(self):
        """停止调度器"""
        if not self._running:
            return

        self._running = False
        if self._refresh_task:
            self._refresh_task.cancel()
        if self._cleanup_task:
            self._cleanup_task.cancel()
        logger.info("Scheduler: stopped")


_scheduler: Optional[TokenRefreshScheduler] = None


def get_scheduler(
    refresh_interval_hours: int = 8,
    cleanup_interval_minutes: int = 10,
) -> TokenRefreshScheduler:
    """获取调度器单例"""
    global _scheduler
    if _scheduler is None:
        _scheduler = TokenRefreshScheduler(
            refresh_interval_hours=refresh_interval_hours,
            cleanup_interval_minutes=cleanup_interval_minutes,
        )
    else:
        _scheduler.refresh_interval_hours = refresh_interval_hours
        _scheduler.refresh_interval_seconds = refresh_interval_hours * 3600
        _scheduler.cleanup_interval_minutes = cleanup_interval_minutes
        _scheduler.cleanup_interval_seconds = cleanup_interval_minutes * 60
    return _scheduler


__all__ = ["TokenRefreshScheduler", "get_scheduler"]
