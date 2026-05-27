// AG-UI 客户端适配器 — Phase 4 接入 v2 前端 UI 时使用
// 当前 v2 /api/v2/chat/stream 端点已就绪，此 composable 待 ChatPanel 升级时接入

import { reactive } from 'vue'

type AgentStatus = 'idle' | 'running' | 'done' | 'error'

interface ToolState {
  name: string
  status: 'pending' | 'running' | 'done' | 'error'
  result?: unknown
}

interface AGUIClientState {
  status: AgentStatus
  currentTool: ToolState | null
  toolHistory: ToolState[]
  stateDeltas: Record<string, unknown>
  error: string | null
  confidence: number | null
  assumptions: string[]
}

export function useAGUIClient() {
  const state = reactive<AGUIClientState>({
    status: 'idle',
    currentTool: null,
    toolHistory: [],
    stateDeltas: {},
    error: null,
    confidence: null,
    assumptions: [],
  })

  let abortController: AbortController | null = null

  async function runAgent(input: string, dbConnectionId?: string, model?: string) {
    state.status = 'running'
    state.toolHistory = []
    state.error = null
    state.confidence = null
    state.assumptions = []

    abortController = new AbortController()
    const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'

    const response = await fetch(`${baseUrl}/v2/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({
        message: input,
        db_connection_id: dbConnectionId || undefined,
        model: model || undefined,
      }),
      signal: abortController.signal,
    })

    if (!response.ok) {
      state.status = 'error'
      state.error = `HTTP ${response.status}`
      return
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
        if (!line.startsWith('data: ')) continue
        const json = line.slice(6).trim()
        if (!json) continue
        try {
          const event = JSON.parse(json)
          handleEvent(event)
        } catch { /* ignore malformed JSON */ }
      }
    }
  }

  function handleEvent(event: Record<string, unknown>) {
    switch (event.type) {
      case 'RUN_STARTED':
        state.status = 'running'
        break
      case 'TOOL_CALL_START':
        state.currentTool = {
          name: (event.tool_name as string) || 'unknown',
          status: 'running',
        }
        break
      case 'TOOL_CALL_END':
        if (state.currentTool) {
          state.currentTool.status = 'done'
          state.toolHistory.push({ ...state.currentTool })
          state.currentTool = null
        }
        break
      case 'TOOL_CALL_RESULT':
        if (state.currentTool) {
          state.currentTool.result = event.result
        }
        break
      case 'STATE_DELTA':
        state.stateDeltas[event.path as string] = event.value
        if (event.path === '/output') {
          const output = event.value as Record<string, unknown> | undefined
          state.confidence = (output?.confidence as number) ?? null
          state.assumptions = (output?.assumptions as string[]) ?? []
        }
        break
      case 'RUN_FINISHED':
        state.status = 'done'
        break
      case 'RUN_ERROR':
        state.status = 'error'
        state.error = (event.message as string) || 'Unknown error'
        break
    }
  }

  function cancel() {
    abortController?.abort()
    const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'
    fetch(`${baseUrl}/v2/chat/cancel`, { method: 'POST' }).catch(() => {})
  }

  return { state, runAgent, cancel }
}
