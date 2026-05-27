"""ConnectionHealthChecker 单元测试。"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.connection_health_checker import ConnectionHealthChecker


class TestConnectionHealthChecker:
    async def test_subscribe_returns_queue(self):
        checker = ConnectionHealthChecker()
        q = checker.subscribe()
        assert isinstance(q, asyncio.Queue)

    async def test_unsubscribe_removes_queue(self):
        checker = ConnectionHealthChecker()
        q = checker.subscribe()
        checker.unsubscribe(q)
        # 再次 subscribe 应该只有一个
        q2 = checker.subscribe()
        checker.unsubscribe(q2)

    async def test_broadcast_delivers_to_all_subscribers(self):
        checker = ConnectionHealthChecker()
        q1 = checker.subscribe()
        q2 = checker.subscribe()

        event = {"type": "status", "connection_id": "abc", "status": "ok"}
        await checker._broadcast(event)

        got1 = await asyncio.wait_for(q1.get(), timeout=1)
        got2 = await asyncio.wait_for(q2.get(), timeout=1)

        assert got1 == event
        assert got2 == event

    async def test_broadcast_drops_old_on_full_queue(self):
        checker = ConnectionHealthChecker()
        q = asyncio.Queue(maxsize=1)

        checker._subscribers.append(q)
        await q.put({"type": "old"})

        new_event = {"type": "status", "connection_id": "x", "status": "ok"}
        await checker._broadcast(new_event)

        got = await asyncio.wait_for(q.get(), timeout=1)
        assert got == new_event

    async def test_start_stop_lifecycle(self):
        checker = ConnectionHealthChecker(probe_interval=60)
        with patch.object(checker, "_probe_all", new_callable=AsyncMock) as mock_probe:
            await checker.start()
            await asyncio.sleep(0.05)  # 给 task 一点时间执行
            mock_probe.assert_called()
            await checker.stop()

    async def test_get_health_checker_singleton(self):
        from app.services.connection_health_checker import get_health_checker

        h1 = get_health_checker()
        h2 = get_health_checker()
        assert h1 is h2
