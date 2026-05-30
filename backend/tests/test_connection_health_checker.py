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

    # ── 新增测试：stop() 生命周期 ──

    async def test_stop_sends_closed_event(self):
        """stop() 应向所有订阅者发送 closed 事件。"""
        checker = ConnectionHealthChecker(probe_interval=60)
        q = checker.subscribe()
        await checker.start()
        await asyncio.sleep(0.05)
        await checker.stop()
        # 队列中应有 closed 事件
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        assert any(e.get("type") == "closed" for e in events)

    # ── 新增测试：probe_one 广播 ──

    async def test_probe_one_broadcasts_on_status_change(self):
        """_probe_one 在状态变更时应广播事件。"""
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.services.connection_health_checker import ConnectionHealthChecker

        checker = ConnectionHealthChecker()
        q = checker.subscribe()

        mock_conn = MagicMock()
        mock_conn.id = "test-conn-1"
        mock_conn.name = "test-db"
        mock_conn.driver_type = "native"
        mock_conn.connection_tested = True

        with patch(
            "app.services.connection_health_checker.get_cached_status",
            return_value="ok",
        ):
            with patch("app.services.connection_health_checker.set_cached_status"):
                with (
                    patch(
                        "app.services.connection_health_checker.get_connector",
                    ) as mock_get_conn,
                ):
                    mock_connector = MagicMock()
                    mock_connector.test = AsyncMock(
                        return_value=(False, "connection refused"),
                    )
                    mock_get_conn.return_value = mock_connector

                    with patch(
                        (
                            "app.services.connection_health_checker."
                            "_to_connection_config"
                        ),
                    ) as mock_to_config:
                        mock_config = MagicMock()
                        mock_config.connection_timeout = 5
                        mock_to_config.return_value = mock_config

                        await checker._probe_one(mock_conn)

        # 应广播 error 事件
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        status_events = [e for e in events if e.get("type") == "status"]
        assert len(status_events) == 1
        assert status_events[0]["connection_id"] == "test-conn-1"
        assert status_events[0]["status"] == "error"

    async def test_probe_one_no_broadcast_when_status_unchanged(self):
        """状态未变更时不应广播。"""
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.services.connection_health_checker import ConnectionHealthChecker

        checker = ConnectionHealthChecker()
        q = checker.subscribe()

        mock_conn = MagicMock()
        mock_conn.id = "test-conn-1"
        mock_conn.name = "test-db"
        mock_conn.driver_type = "native"
        mock_conn.connection_tested = True

        # old_status = "ok", new_status = "ok" -> no change
        with patch(
            "app.services.connection_health_checker.get_cached_status",
            return_value="ok",
        ):
            with patch("app.services.connection_health_checker.set_cached_status"):
                with (
                    patch(
                        "app.services.connection_health_checker.get_connector",
                    ) as mock_get_conn,
                ):
                    mock_connector = MagicMock()
                    mock_connector.test = AsyncMock(
                        return_value=(True, "connected"),
                    )
                    mock_get_conn.return_value = mock_connector

                    with patch(
                        (
                            "app.services.connection_health_checker."
                            "_to_connection_config"
                        ),
                    ) as mock_to_config:
                        mock_config = MagicMock()
                        mock_to_config.return_value = mock_config

                        await checker._probe_one(mock_conn)

        events = []
        while not q.empty():
            events.append(q.get_nowait())
        status_events = [e for e in events if e.get("type") == "status"]
        assert len(status_events) == 0

    # ── 新增测试：缓存重置 ──

    async def test_reset_cache_for_tests(self):
        """reset_cache_for_tests 应清空缓存。"""
        from app.services.connection_cache import (
            get_cached_status,
            is_testing,
            reset_cache_for_tests,
            set_cached_status,
            set_testing,
        )

        set_cached_status("conn-1", "ok")
        set_testing("conn-2")
        assert get_cached_status("conn-1") == "ok"
        assert is_testing("conn-2") is True

        reset_cache_for_tests()

        assert get_cached_status("conn-1") is None
        assert is_testing("conn-2") is False

    async def test_reset_for_tests_resets_singleton(self):
        """_reset_for_tests 应重置全局单例。"""
        from app.services.connection_health_checker import (
            ConnectionHealthChecker,
            get_health_checker,
        )

        h1 = get_health_checker()
        ConnectionHealthChecker._reset_for_tests()
        h2 = get_health_checker()
        assert h1 is not h2
