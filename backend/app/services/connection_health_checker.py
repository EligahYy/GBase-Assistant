"""后台连接健康检查器。每 N 秒主动探测所有活跃的 GBase 连接，
状态变更时通过 asyncio.Queue 广播事件，供 SSE 端点消费。"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from sqlalchemy import select

from app.api.connections import _to_connection_config
from app.database import async_session_factory
from app.db_connectors.connector_factory import get_connector
from app.models.connection import DbConnection
from app.services.connection_cache import get_cached_status, reset_cache_for_tests, set_cached_status

logger = logging.getLogger(__name__)

# ── 公开事件类型 ──
# 消费者通过 subscribe() 获取队列引用，监听 dict 事件
# 事件格式: {"type": "status", "connection_id": str, "status": "ok"|"error"}
#          {"type": "heartbeat"}


class ConnectionHealthChecker:
    """后台连接健康检查器（单例模式）。"""

    def __init__(self, probe_interval: float = 10.0, test_timeout: int = 2):
        self._probe_interval = probe_interval
        self._test_timeout = test_timeout
        self._task: asyncio.Task | None = None
        self._subscribers: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        """返回一个队列，调用方通过 `await q.get()` 接收事件。

        所有订阅者共享同一份事件广播（扇出）。"""
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    async def _broadcast(self, event: dict) -> None:
        """向所有订阅者广播事件。满队列丢弃旧事件（非阻塞 put）。"""
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # 消费者太慢，丢弃旧事件
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    async def _probe_one(self, conn) -> None:
        """探测单个连接。"""
        connector = get_connector(conn.driver_type)
        if not connector:
            logger.warning(
                "HealthChecker: 连接 %s 的驱动 %s 不可用",
                conn.name,
                conn.driver_type,
            )
            return

        old_status = get_cached_status(conn.id)
        if old_status is None:
            old_status = "ok" if conn.connection_tested else "unknown"

        config = _to_connection_config(conn)
        config.connection_timeout = self._test_timeout

        try:
            ok, _ = await asyncio.wait_for(
                connector.test(config),
                timeout=self._test_timeout + 1,
            )
        except TimeoutError:
            ok = False
        except Exception:
            ok = False

        new_status = "ok" if ok else "error"
        set_cached_status(conn.id, new_status)

        if old_status != new_status:
            logger.info(
                "HealthChecker: 连接 %s 状态变更 %s -> %s",
                conn.name,
                old_status,
                new_status,
            )
            await self._broadcast(
                {
                    "type": "status",
                    "connection_id": conn.id,
                    "status": new_status,
                }
            )

    async def _probe_all(self) -> None:
        """并行探测所有活跃连接并广播变更。"""
        try:
            async with async_session_factory() as session:
                result = await session.execute(select(DbConnection).where(DbConnection.is_active.is_(True)))
                connections = result.scalars().all()
        except Exception as e:
            logger.warning("HealthChecker: 查询连接列表失败: %s", e)
            return

        targets = [c for c in connections if c.driver_type != "manual"]
        if targets:
            await asyncio.gather(*[self._probe_one(c) for c in targets], return_exceptions=True)

    async def _run(self) -> None:
        """后台循环。"""
        logger.info(
            "HealthChecker 已启动 (interval=%ss, timeout=%ss)",
            self._probe_interval,
            self._test_timeout,
        )
        while True:
            try:
                await self._probe_all()
            except Exception as e:
                logger.error("HealthChecker: 探测异常: %s", e)
            # 发送心跳，让前端知道 SSE 连接仍活跃
            await self._broadcast({"type": "heartbeat"})
            await asyncio.sleep(self._probe_interval)

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        # 清空订阅者（让 SSE 连接正常关闭）
        for q in self._subscribers:
            await q.put({"type": "closed"})
        self._subscribers.clear()
        logger.info("HealthChecker 已停止")

    @classmethod
    def _reset_for_tests(cls) -> None:
        """仅测试使用：重置全局单例和缓存。"""
        global _health_checker
        _health_checker = None
        reset_cache_for_tests()


# 全局单例
_health_checker: ConnectionHealthChecker | None = None


def get_health_checker() -> ConnectionHealthChecker:
    global _health_checker
    if _health_checker is None:
        _health_checker = ConnectionHealthChecker()
    return _health_checker
