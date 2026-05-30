"""连接状态缓存（内存），供 HealthChecker 和 API 层共享。"""

from __future__ import annotations

import time

# key: connection_id, value: (monotonic_timestamp, 'ok' | 'error')
_status_cache: dict[str, tuple[float, str]] = {}
CACHE_TTL = 15  # 缓存有效期 15 秒
_testing_locks: set[str] = set()


def get_cached_status(connection_id: str) -> str | None:
    """读取缓存的状态，超过 TTL 返回 None。"""
    entry = _status_cache.get(connection_id)
    if entry and (time.monotonic() - entry[0]) < CACHE_TTL:
        return entry[1]
    return None


def set_cached_status(connection_id: str, status: str) -> None:
    """设置连接缓存状态。"""
    _status_cache[connection_id] = (time.monotonic(), status)


def is_testing(connection_id: str) -> bool:
    """检查连接是否正在被测试。"""
    return connection_id in _testing_locks


def set_testing(connection_id: str) -> None:
    """标记连接为测试中。"""
    _testing_locks.add(connection_id)


def clear_testing(connection_id: str) -> None:
    """清除连接测试标记。"""
    _testing_locks.discard(connection_id)


def reset_cache_for_tests() -> None:
    """仅测试使用：清空所有缓存状态。"""
    _status_cache.clear()
    _testing_locks.clear()
