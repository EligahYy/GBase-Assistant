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
    // Auto-select first connection if none selected
    if (!activeConnectionId.value && connections.value.length > 0) {
      activeConnectionId.value = connections.value[0]?.id ?? null
    }
    // Clear selection if the active connection no longer exists
    if (activeConnectionId.value && !connections.value.find(c => c.id === activeConnectionId.value)) {
      activeConnectionId.value = connections.value.length > 0 ? connections.value[0].id : null
    }
    // Clean up stale status entries for deleted connections
    const validIds = new Set(connections.value.map(c => c.id))
    const newMap: Record<string, ConnStatus> = {}
    for (const [id, status] of Object.entries(connStatusMap.value)) {
      if (validIds.has(id)) newMap[id] = status
    }
    connStatusMap.value = newMap
  }

  function setActiveConnection(id: string | null) {
    activeConnectionId.value = id
  }

  // ── SSE 连接管理 ──
  function startStatusStream() {
    if (sseController) return // 已连接

    const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'

    // 先获取全量快照作为基线，再启动 SSE（避免 SSE 事件被快照覆盖）
    getConnectionsStatus().then(resp => {
      const newMap: Record<string, ConnStatus> = {}
      for (const item of resp.connections) {
        if (item.status === 'ok') newMap[item.id] = 'ok'
        else if (item.status === 'testing') newMap[item.id] = 'testing'
        else newMap[item.id] = 'error'
      }
      connStatusMap.value = newMap
    }).catch(() => {})

    // 快照请求发出后再启动 SSE
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
