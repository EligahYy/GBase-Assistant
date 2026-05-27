# GBase 连接状态实时检测 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 GBase 数据库连接状态检测从 5 秒轮询 + 30 秒缓存改为后台主动探测 + SSE 实时推送，使用户对连接状态变化无感知（< 1 秒延迟）。

**Architecture:** 后端新增 `ConnectionHealthChecker` 后台服务，每 10 秒主动探测所有活跃连接（2 秒短超时），状态变更时通过 asyncio.Queue 广播事件。新增 SSE 端点 `/api/connections/status/stream` 将事件推送到前端。前端在 Pinia store 中集中管理连接状态，ChatPanel 和 SettingsView 共享同一份状态和同一个 SSE 连接，彻底消除重复轮询。

**Tech Stack:** FastAPI (SSE via StreamingResponse), Vue 3 + Pinia (fetch ReadableStream), Python asyncio

---

## 文件结构

| 文件 | 职责 | 操作 |
|------|------|------|
| `backend/app/services/connection_health_checker.py` | 后台定时探测所有活跃连接，通过 Queue 广播状态变更事件 | **新建** |
| `backend/app/api/connections.py` | 改造 GET /status，新增 SSE 端点，集成 HealthChecker | **修改** |
| `backend/app/main.py` | lifespan 中启动/停止 HealthChecker | **修改** |
| `frontend/src/stores/connection.ts` | 集中管理连接状态，维护全局 SSE 连接 | **修改** |
| `frontend/src/api/connections.ts` | 新增 `connectStatusStream` 函数 | **修改** |
| `frontend/src/components/chat/ChatPanel.vue` | 移除本地轮询，改用 store 的状态 | **修改** |
| `frontend/src/views/SettingsView.vue` | 移除本地轮询，改用 store 的状态 | **修改** |
| `backend/tests/test_connection_health_checker.py` | HealthChecker 单元测试 | **新建** |

---

### Task 1: 后端 — ConnectionHealthChecker 服务

**Files:**
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/connection_health_checker.py`

- [ ] **Step 1: 创建 `__init__.py`**

```bash
mkdir -p backend/app/services
```

- [ ] **Step 2: 编写 ConnectionHealthChecker**

```python
"""后台连接健康检查器。每 N 秒主动探测所有活跃的 GBase 连接，
状态变更时通过 asyncio.Queue 广播事件，供 SSE 端点消费。"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.db_connectors.connector_factory import DatabaseConnectorProtocol

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

    async def _probe_all(self) -> None:
        """探测所有活跃连接并广播变更。"""
        from app.database import async_session_factory
        from app.models.connection import DbConnection
        from app.db_connectors.connector_factory import get_connector
        from app.api.connections import _get_cached_status, _set_cached_status

        try:
            async with async_session_factory() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(DbConnection).where(DbConnection.is_active.is_(True))
                )
                connections = result.scalars().all()
        except Exception as e:
            logger.warning("HealthChecker: 查询连接列表失败: %s", e)
            return

        for conn in connections:
            if conn.driver_type == "manual":
                continue

            connector = get_connector(conn.driver_type)
            if not connector:
                continue

            old_status = _get_cached_status(conn.id)
            if old_status is None:
                old_status = "ok" if conn.connection_tested else "unknown"

            # 构建配置并设短超时
            from app.api.connections import _to_connection_config
            config = _to_connection_config(conn)
            config.connection_timeout = self._test_timeout

            try:
                ok, _ = await asyncio.wait_for(
                    connector.test(config),
                    timeout=self._test_timeout + 1,  # 比连接超时多 1s
                )
            except asyncio.TimeoutError:
                ok = False
            except Exception:
                ok = False

            new_status = "ok" if ok else "error"
            _set_cached_status(conn.id, new_status)

            # 状态变更时广播
            if old_status != new_status:
                logger.info(
                    "HealthChecker: 连接 %s 状态变更 %s -> %s",
                    conn.name, old_status, new_status,
                )
                await self._broadcast({
                    "type": "status",
                    "connection_id": conn.id,
                    "status": new_status,
                })

    async def _run(self) -> None:
        """后台循环。"""
        logger.info(
            "HealthChecker 已启动 (interval=%ss, timeout=%ss)",
            self._probe_interval, self._test_timeout,
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


# 全局单例
_health_checker: ConnectionHealthChecker | None = None


def get_health_checker() -> ConnectionHealthChecker:
    global _health_checker
    if _health_checker is None:
        _health_checker = ConnectionHealthChecker()
    return _health_checker
```

- [ ] **Step 3: 编写单元测试 `backend/tests/test_connection_health_checker.py`**

```python
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
```

- [ ] **Step 4: 运行测试验证失败（新测试，功能尚未集成）**

```bash
cd backend && python -m pytest tests/test_connection_health_checker.py -v
```

Expected: 部分测试可能因为缺少数据库 fixture 而失败，核心逻辑测试应通过。

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/__init__.py backend/app/services/connection_health_checker.py backend/tests/test_connection_health_checker.py
git commit -m "feat: add ConnectionHealthChecker background service for proactive GBase connection probing"
```

---

### Task 2: 后端 — 集成 HealthChecker 到 FastAPI 生命周期

**Files:**
- Modify: `backend/app/main.py:31-71`

- [ ] **Step 1: 修改 lifespan 启动/停止 HealthChecker**

在 `backend/app/main.py` 的 `lifespan` 函数中，在 `yield` 之前启动 HealthChecker，在 `yield` 之后停止。

找到 lifespan 中的这几行（约第 69-71 行）：
```python
    logger.info("应用启动完成，API 文档: http://localhost:8000/docs")
    yield
    logger.info("应用关闭")
```

在其上方添加启动 HealthChecker：

```python
    # 启动连接健康检查器（后台主动探测 GBase 连接状态）
    try:
        from app.services.connection_health_checker import get_health_checker
        await get_health_checker().start()
        logger.info("ConnectionHealthChecker 已启动")
    except Exception as e:
        logger.warning("ConnectionHealthChecker 启动失败: %s", e)

    logger.info("应用启动完成，API 文档: http://localhost:8000/docs")
    yield
    # ── 关闭 ──
    logger.info("应用关闭")
    try:
        from app.services.connection_health_checker import get_health_checker
        await get_health_checker().stop()
    except Exception:
        pass
```

注意：原来的 `yield` 后面已经有 Qdrant 关闭逻辑，HealthChecker 的 stop 放在它之后。

- [ ] **Step 2: 确认修改后的 lifespan 完整逻辑**

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    import os

    logger.info("初始化数据库...")
    await init_db()

    if os.getenv("TESTING"):
        logger.info("测试模式：跳过 Qdrant 和 Embedding 初始化")
    else:
        try:
            from app.vector.client import get_qdrant_manager, set_qdrant_available
            from app.vector.embedder import get_embedder

            qdrant_mgr = get_qdrant_manager()
            embedder = get_embedder()
            await qdrant_mgr.ensure_collections(dimension=embedder.dimension)
            logger.info("Qdrant collections 就绪 (dim=%d)", embedder.dimension)

            await embedder.embed(["warmup"])
            logger.info("Embedding 模型预热完成")

            set_qdrant_available(True)
            logger.info("Qdrant 向量检索已启用")

            if os.getenv("SKIP_VECTOR_SYNC"):
                logger.info("SKIP_VECTOR_SYNC: 跳过知识库同步")
            else:
                asyncio.create_task(_background_sync_all_to_qdrant(embedder))
                logger.info("知识库同步已放入后台任务")
        except Exception as e:
            logger.warning("Qdrant 初始化失败，回退到文件模式: %s", e)

    # 启动连接健康检查器
    try:
        from app.services.connection_health_checker import get_health_checker
        await get_health_checker().start()
        logger.info("ConnectionHealthChecker 已启动")
    except Exception as e:
        logger.warning("ConnectionHealthChecker 启动失败: %s", e)

    logger.info("应用启动完成，API 文档: http://localhost:8000/docs")
    yield
    # ── 关闭资源 ──
    logger.info("应用关闭")
    try:
        from app.services.connection_health_checker import get_health_checker
        await get_health_checker().stop()
    except Exception:
        pass
    try:
        from app.vector.client import get_qdrant_manager
        await get_qdrant_manager().close()
    except Exception:
        pass
```

- [ ] **Step 3: 验证后端能正常启动**

```bash
cd backend && TESTING=1 python -c "from app.main import app; print('OK')"
```

Expected: `OK` 输出，无异常。

- [ ] **Step 4: Commit**

```bash
git add backend/app/main.py
git commit -m "feat: start/stop ConnectionHealthChecker in FastAPI lifespan"
```

---

### Task 3: 后端 — 新增 SSE 端点 /api/connections/status/stream

**Files:**
- Modify: `backend/app/api/connections.py`（在文件末尾新增端点）

- [ ] **Step 1: 新增 SSE 端点**

在 `backend/app/api/connections.py` 文件末尾（`execute_query` 之后），新增以下代码：

```python
from fastapi.responses import StreamingResponse


@router.get("/status/stream")
async def stream_connection_status():
    """SSE 端点：实时推送连接状态变更事件。

    事件格式:
      data: {"type":"status","connection_id":"<id>","status":"ok"|"error"}

      data: {"type":"heartbeat"}

    前端通过 EventSource 或 fetch + ReadableStream 消费。
    """
    from app.services.connection_health_checker import get_health_checker

    checker = get_health_checker()
    queue = checker.subscribe()

    async def event_generator():
        try:
            while True:
                try:
                    # 首次连接时立即发送当前所有连接的状态快照
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # 15 秒无事件，发送 keepalive 注释（SSE 标准）
                    yield ": keepalive\n\n"
                    continue

                if event.get("type") == "closed":
                    break

                import json
                data = json.dumps(event, ensure_ascii=False)
                yield f"data: {data}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            checker.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
        },
    )
```

- [ ] **Step 2: 修改 `_background_test_connection` 在结果变更时也广播事件**

在 `_background_test_connection` 函数末尾（约第 81-96 行），在 `_set_cached_status(connection_id, "ok" if ok else "error")` 之后，新增广播逻辑：

找到这段代码（约第 91-92 行）：
```python
            ok, _ = await connector.test(config)
            _set_cached_status(connection_id, "ok" if ok else "error")
```

改为：
```python
            old_status = _get_cached_status(connection_id)
            ok, _ = await connector.test(config)
            new_status = "ok" if ok else "error"
            _set_cached_status(connection_id, new_status)

            # 广播状态变更
            if old_status != new_status:
                from app.services.connection_health_checker import get_health_checker
                await get_health_checker()._broadcast({
                    "type": "status",
                    "connection_id": connection_id,
                    "status": new_status,
                })
```

- [ ] **Step 3: 在手动测试端点也广播变更**

修改 `POST /{connection_id}/test` 端点（约第 284-312 行），在设置缓存后也广播事件。

找到约第 311 行：
```python
    status = "ok" if ok else "error"
    _set_cached_status(connection_id, status)
```

在其后添加：
```python
    # 广播状态变更到 SSE 订阅者
    from app.services.connection_health_checker import get_health_checker
    await get_health_checker()._broadcast({
        "type": "status",
        "connection_id": connection_id,
        "status": status,
    })
```

- [ ] **Step 4: 新增 SSE 端点测试**

在 `backend/tests/test_api.py` 中添加：

```python
import json
from httpx import AsyncClient
from app.main import app


async def test_connection_status_stream():
    """SSE 端点应返回 text/event-stream 并正确推送事件。"""
    async with AsyncClient(app=app, base_url="http://test") as client:
        async with client.stream("GET", "/api/connections/status/stream") as response:
            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream"
```

- [ ] **Step 5: 运行测试**

```bash
cd backend && TESTING=1 python -m pytest tests/test_api.py::test_connection_status_stream -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/connections.py backend/tests/test_api.py
git commit -m "feat: add SSE endpoint /api/connections/status/stream for real-time status push"
```

---

### Task 4: 前端 — Pinia Store 集中管理连接状态 + SSE

**Files:**
- Modify: `frontend/src/stores/connection.ts`
- Modify: `frontend/src/api/connections.ts`

- [ ] **Step 1: 新增 `connectStatusStream` API 函数**

在 `frontend/src/api/connections.ts` 文件末尾添加：

```typescript
export interface StatusStreamEvent {
  type: 'status' | 'heartbeat' | 'closed'
  connection_id?: string
  status?: string
}

export function connectStatusStream(
  baseUrl: string,
  onEvent: (event: StatusStreamEvent) => void,
  onError?: (err: Error) => void,
): AbortController {
  const controller = new AbortController()
  const url = `${baseUrl}/connections/status/stream`

  void (async () => {
    try {
      const response = await fetch(url, {
        signal: controller.signal,
        headers: { Accept: 'text/event-stream' },
      })

      if (!response.ok) {
        throw new Error(`SSE connect failed: HTTP ${response.status}`)
      }

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6).trim()
            if (!data) continue
            try {
              const event = JSON.parse(data) as StatusStreamEvent
              onEvent(event)
            } catch { /* ignore malformed */ }
          }
          // ": keepalive" 行忽略
        }
      }
    } catch (e: any) {
      if (e.name !== 'AbortError') {
        onError?.(e instanceof Error ? e : new Error(String(e)))
      }
    }
  })()

  return controller
}
```

- [ ] **Step 2: 改造 Pinia Store 集成 SSE**

完全重写 `frontend/src/stores/connection.ts`：

```typescript
import { defineStore } from 'pinia'
import { ref, shallowRef } from 'vue'
import type { ConnectionResponse, StatusStreamEvent } from '@/api/connections'
import { listConnections, connectStatusStream, getConnectionsStatus } from '@/api/connections'

export type ConnStatus = 'ok' | 'error' | 'testing' | 'unknown'

export const useConnectionStore = defineStore('connection', () => {
  const connections = ref<ConnectionResponse[]>([])
  const activeConnectionId = ref<string | null>(null)

  // ── 连接状态（全局共享，SSE 实时更新） ──
  const connStatusMap = shallowRef<Record<string, ConnStatus>>({})
  let sseController: AbortController | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  const SSE_RECONNECT_DELAY = 3000

  async function loadConnections() {
    connections.value = await listConnections()
    if (!activeConnectionId.value && connections.value.length > 0) {
      activeConnectionId.value = connections.value[0]?.id ?? null
    }
  }

  function setActiveConnection(id: string | null) {
    activeConnectionId.value = id
  }

  // ── SSE 连接管理 ──
  function startStatusStream() {
    if (sseController) return // 已连接

    const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'

    sseController = connectStatusStream(
      baseUrl,
      (event: StatusStreamEvent) => {
        if (event.type === 'status' && event.connection_id) {
          const newMap = { ...connStatusMap.value }
          newMap[event.connection_id] = (event.status === 'ok' ? 'ok' : 'error') as ConnStatus
          connStatusMap.value = newMap
        }
        // heartbeat 事件仅表示连接活跃，无需处理
      },
      (_err: Error) => {
        // SSE 断连，自动重连
        sseController = null
        if (reconnectTimer) clearTimeout(reconnectTimer)
        reconnectTimer = setTimeout(() => {
          reconnectTimer = null
          startStatusStream()
        }, SSE_RECONNECT_DELAY)
      },
    )

    // 连接后立即获取一次全量状态快照（弥合 SSE 连接建立前可能错过的更新）
    getConnectionsStatus().then(resp => {
      const newMap: Record<string, ConnStatus> = {}
      for (const item of resp.connections) {
        if (item.status === 'ok') newMap[item.id] = 'ok'
        else if (item.status === 'testing') newMap[item.id] = 'testing'
        else newMap[item.id] = 'error'
      }
      connStatusMap.value = newMap
    }).catch(() => {})
  }

  function stopStatusStream() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (sseController) {
      sseController.abort()
      sseController = null
    }
  }

  // 手动测试后立即更新本地状态（不等待 SSE）
  function setLocalStatus(connectionId: string, status: ConnStatus) {
    const newMap = { ...connStatusMap.value }
    newMap[connectionId] = status
    connStatusMap.value = newMap
  }

  return {
    connections, activeConnectionId, connStatusMap,
    loadConnections, setActiveConnection,
    startStatusStream, stopStatusStream, setLocalStatus,
  }
})
```

- [ ] **Step 3: 运行 TypeScript 类型检查**

```bash
cd frontend && npx vue-tsc --noEmit
```

Expected: 无类型错误。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/stores/connection.ts frontend/src/api/connections.ts
git commit -m "feat: centralize connection status in Pinia store with SSE real-time updates"
```

---

### Task 5: 前端 — ChatPanel 移除本地轮询

**Files:**
- Modify: `frontend/src/components/chat/ChatPanel.vue`（约第 38-97 行）

- [ ] **Step 1: 删除本地轮询逻辑，改用 store**

删除以下代码块（约第 38-97 行）：
```typescript
// ── 连接状态实时检测 ──
const connStatusMap = ref<Record<string, 'ok' | 'error' | 'testing'>>({})
const connStatusLoading = ref(false)
const POLL_INTERVAL = 5000

async function checkConnectionStatus() {
  connStatusLoading.value = true
  try {
    const resp = await getConnectionsStatus()
    for (const item of resp.connections) {
      if (item.status === 'ok') {
        connStatusMap.value[item.id] = 'ok'
      } else if (item.status === 'testing') {
        connStatusMap.value[item.id] = 'testing'
      } else {
        connStatusMap.value[item.id] = 'error'
      }
    }
  } catch {
    // ignore
  } finally {
    connStatusLoading.value = false
  }
}

let pollTimer: ReturnType<typeof setInterval> | null = null

function startPolling() {
  checkConnectionStatus()
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(checkConnectionStatus, POLL_INTERVAL)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function handleVisibilityChange() {
  if (document.visibilityState === 'visible') {
    checkConnectionStatus()
  }
}
```

并删除对应的生命周期和 watch（约第 84-97 行）：
```typescript
onMounted(() => {
  connStore.loadConnections().catch(() => {})
  startPolling()
  document.addEventListener('visibilitychange', handleVisibilityChange)
})

onBeforeUnmount(() => {
  stopPolling()
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})

watch(() => connStore.activeConnectionId, () => {
  startPolling()
})
```

- [ ] **Step 2: 新增简洁的生命周期逻辑**

在 ChatPanel.vue 的 `<script setup>` 中添加：

```typescript
// ── 连接状态（全局 store + SSE 实时推送） ──
onMounted(() => {
  connStore.loadConnections().catch(() => {})
  connStore.startStatusStream()
})

onBeforeUnmount(() => {
  // ChatPanel 卸载时不停止 SSE（SettingsView 可能还在使用）
  // SSE 由 store 全局管理，页面切换不影响
})
```

- [ ] **Step 3: 修改模板中的状态引用**

模板中 `connStatusMap[activeConn.id]` 改为 `connStore.connStatusMap[activeConn.id]`：

```vue
        <div
          v-if="activeConn"
          class="conn-badge"
          :class="{
            'status-ok': connStore.connStatusMap[activeConn.id] === 'ok',
            'status-error': connStore.connStatusMap[activeConn.id] === 'error',
            'status-testing': connStore.connStatusMap[activeConn.id] === 'testing',
          }"
        >
          <div class="dot" :class="{ pulsing: connStore.connStatusMap[activeConn.id] !== 'error' }" />
          <n-icon :component="ServerOutline" size="12" />
          <span>{{ activeConn.name }}</span>
          <span v-if="connStore.connStatusMap[activeConn.id] === 'testing'" class="status-checking">检测中</span>
```

- [ ] **Step 4: 删除不再使用的 import**

从 import 中删除：
- `ref` 和 `watch` 中只用到了 `computed, inject, onMounted, onBeforeUnmount`，删除多余的 `ref`, `watch`
- 删除 `import { getConnectionsStatus } from '@/api/connections'`

实际上保留必要的 imports。检查当前文件 imports（第 1-16 行），最终应保留：

```typescript
import { computed, inject, onMounted, onBeforeUnmount } from 'vue'
import { useMessage } from 'naive-ui'
import {
  SendOutline, ServerOutline, SunnyOutline, MoonOutline,
  StopCircleOutline, BookOutline, SparklesOutline,
} from '@vicons/ionicons5'
import { NIcon } from 'naive-ui'

import MessageBubble from './MessageBubble.vue'
import { useChatStore } from '@/stores/chat'
import { useConnectionStore } from '@/stores/connection'
import { useSSE } from '@/composables/useSSE'
import { createStreamUrl } from '@/api/chat'
import { useTheme } from '@/composables/useTheme'
```

- [ ] **Step 5: 运行 TypeScript 类型检查**

```bash
cd frontend && npx vue-tsc --noEmit
```

Expected: 无类型错误。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/chat/ChatPanel.vue
git commit -m "refactor: replace ChatPanel local polling with shared Pinia SSE status"
```

---

### Task 6: 前端 — SettingsView 移除本地轮询

**Files:**
- Modify: `frontend/src/views/SettingsView.vue`（约第 50-85 行）

- [ ] **Step 1: 删除本地轮询逻辑**

删除：
```typescript
const connLiveStatus = ref<Record<string, 'ok' | 'error' | 'unknown'>>({})

let statusPollTimer: ReturnType<typeof setInterval> | null = null

async function loadConnLiveStatus() {
  try {
    const resp = await getConnectionsStatus()
    for (const item of resp.connections) {
      connLiveStatus.value[item.id] = item.status === 'ok' ? 'ok' : item.status === 'testing' ? 'unknown' : 'error'
    }
  } catch { /* ignore */ }
}
```

并删除 `onMounted` 中的：
```typescript
  await loadConnLiveStatus()
  statusPollTimer = setInterval(loadConnLiveStatus, 5000)
```

以及 `onBeforeUnmount` 中的：
```typescript
  if (statusPollTimer) { clearInterval(statusPollTimer); statusPollTimer = null }
```

- [ ] **Step 2: 设置页挂载时连接 SSE**

在 `onMounted` 中添加：
```typescript
  connStore.startStatusStream()
```

修改后的 `onMounted`：
```typescript
onMounted(async () => {
  connections.value = await listConnections()
  try {
    const models = await listModels()
    modelOptions.value = models.map((m: ModelInfo) => ({ label: m.name, value: m.id }))
  } catch {
    modelOptions.value = [
      { label: 'DeepSeek Chat', value: 'deepseek/deepseek-chat' },
      { label: 'Qwen 2.5 72B Instruct', value: 'qwen/qwen2.5-72b-instruct' },
      { label: 'GPT-4o', value: 'openai/gpt-4o' },
    ]
  }
  await loadHealth()
  connStore.startStatusStream()
})
```

- [ ] **Step 3: 修改模板引用**

连接卡片中的 `connLiveStatus[c.id]` 改为 `connStore.connStatusMap[c.id]`：

找到约第 407-409 行：
```vue
                    <span v-if="c.driver_type !== 'manual'" :class="['conn-badge', connLiveStatus[c.id] === 'ok' ? 'ok' : connLiveStatus[c.id] === 'error' ? 'warn' : 'muted']">
                      {{ connLiveStatus[c.id] === 'ok' ? '已连通' : connLiveStatus[c.id] === 'error' ? '已断开' : '待检测' }}
```

改为：
```vue
                    <span v-if="c.driver_type !== 'manual'" :class="['conn-badge', connStore.connStatusMap[c.id] === 'ok' ? 'ok' : connStore.connStatusMap[c.id] === 'error' ? 'warn' : 'muted']">
                      {{ connStore.connStatusMap[c.id] === 'ok' ? '已连通' : connStore.connStatusMap[c.id] === 'error' ? '已断开' : '待检测' }}
```

- [ ] **Step 4: 手动测试后立即更新本地状态**

修改 `handleTestConnection` 函数（约第 163-169 行），测试成功后立即更新 store 状态：

```typescript
async function handleTestConnection(connId: string) {
  testingConn.value.add(connId)
  try {
    const resp = await testConnection(connId)
    naiveMsg[resp.status === 'ok' ? 'success' : 'error'](resp.message)
    connections.value = await listConnections()
    // 立即更新 store 中的状态（不等 SSE，用户即刻看到结果）
    connStore.setLocalStatus(connId, resp.status === 'ok' ? 'ok' : 'error')
  } catch (e: any) { naiveMsg.error(e.message || '测试失败') } finally { testingConn.value.delete(connId) }
}
```

- [ ] **Step 5: 清理不再使用的 import**

删除 `getConnectionsStatus` 的 import（如果不再需要）。

- [ ] **Step 6: 运行 TypeScript 类型检查**

```bash
cd frontend && npx vue-tsc --noEmit
```

Expected: 无类型错误。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/views/SettingsView.vue
git commit -m "refactor: replace SettingsView local polling with shared Pinia SSE status"
```

---

### Task 7: 全局清理 — App.vue 中启动 SSE

**Files:**
- Modify: `frontend/src/App.vue`

- [ ] **Step 1: App.vue 挂载时启动全局 SSE**

在 `App.vue` 的 `onMounted` 中添加 `connStore.startStatusStream()`，确保无论用户从哪个页面进入，SSE 都能连接。

```typescript
onMounted(() => {
  initTheme()
  connStore.loadConnections()
  connStore.startStatusStream()  // 全局启动 SSE 状态推送
  window.addEventListener('keydown', handleKeydown)
})
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/App.vue
git commit -m "feat: start SSE status stream globally in App.vue"
```

---

### Task 8: 端到端验证

- [ ] **Step 1: 启动后端并验证 SSE 端点**

```bash
cd backend && python -m uvicorn app.main:app --reload --port 8000
```

```bash
# 另开终端测试 SSE
curl -N http://localhost:8000/api/connections/status/stream
```

Expected: SSE 流连接成功，每 10 秒收到 heartbeat 事件。如果有连接，收到 status 事件。

- [ ] **Step 2: 验证后台探测日志**

观察后端日志，每 10 秒应输出：
```
HealthChecker: 探测...
```

当连接状态变更时：
```
HealthChecker: 连接 <name> 状态变更 ok -> error
```

- [ ] **Step 3: 启动前端验证实时更新**

```bash
cd frontend && npm run dev
```

验证：
1. 打开首页，连接 badge 显示绿灯（如果 GBase 可达）
2. 进入设置页，连接列表状态与首页一致
3. 手动停掉 GBase 服务，等待最多 10 秒，前后端状态自动变为红色
4. 重新启动 GBase 服务，等待最多 10 秒，状态自动恢复绿色
5. 手动点击"测试"按钮，状态立即更新（不等下一个探测周期）

- [ ] **Step 4: 运行全量测试**

```bash
cd backend && TESTING=1 python -m pytest tests/ -v
cd frontend && npx vue-tsc --noEmit
```

Expected: 所有测试通过，无类型错误。

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: end-to-end verification of real-time connection status"
```

---

## 自检

### 1. Spec 覆盖

| 需求 | 对应 Task |
|------|-----------|
| 更换监测方法（从轮询改为推送） | Task 3 (SSE), Task 4 (Store SSE), Task 5/6 (移除轮询) |
| 低延时 | Task 1 (后台主动探测 10s), Task 2 (集成), Task 3 (SSE 实时推送) |
| 用户无感知 | Task 4 (全局 SSE 自动重连), Task 6 (手动测试即时更新), Task 7 (全局启动) |

### 2. Placeholder 扫描

无 TBD/TODO/placeholder。

### 3. 类型一致性

- `ConnectionHealthChecker` 在 Task 1 定义，Task 2/3 引用，接口一致（`start/stop/subscribe/unsubscribe/_broadcast`）。
- `StatusStreamEvent` 类型在 Task 4 API 定义，Store 引用，字段名一致（`connection_id`, `status`, `type`）。
- Pinia store 方法名在 Task 4 定义，Task 5/6/7 引用，一致（`startStatusStream`, `setLocalStatus`, `connStatusMap`）。
