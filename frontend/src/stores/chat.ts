import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ConversationResponse } from '@/api/chat'
import { listConversations, getConversation, updateConversation, deleteConversation, getConversationSummary, type ConversationSummary, listFolders, createFolder, updateFolder, deleteFolder, batchOperateConversations, type FolderResponse } from '@/api/chat'

export interface ChartConfig {
  type: 'bar' | 'line' | 'pie' | 'scatter'
  title?: string
  x_axis?: { column: string; label: string }
  y_axis?: { column: string; label: string; aggregation?: string }
  group_by?: string | null
}

export interface QueryResult {
  columns: string[]
  rows: unknown[][]
  row_count: number
  execution_time_ms: number
  truncated: boolean
}

export interface ToolCallEntry {
  id: string
  name: string
  args: Record<string, unknown>
  result?: string
  error?: string
  status: 'pending' | 'running' | 'done' | 'error'
  agentName: string
}

export interface StreamEvent {
  type: 'thinking' | 'tool_call' | 'text'
  timestamp: number
  thinking?: string        // for thinking events
  toolCall?: ToolCallEntry  // for tool_call events
  text?: string             // for text events
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  sql?: string | null
  messageType?: string | null
  sources?: string | null
  queryResult?: QueryResult | null
  chartConfig?: ChartConfig | null
  isStreaming?: boolean
  streamContent?: string
  streamSql?: string
  streamEvents?: StreamEvent[]  // chronological event timeline for interleaved display
}

export interface Conversation {
  id: string
  title: string | null
  db_connection_id: string | null
  model_used: string | null
  archived: boolean
  tags: string[]
  created_at: string
}

export const useChatStore = defineStore('chat', () => {
  const conversations = ref<ConversationResponse[]>([])
  const currentConversationId = ref<string | null>(null)
  const messages = ref<Message[]>([])
  const isLoading = ref(false)
  const conversationSummary = ref<ConversationSummary | null>(null)
  const activeFolderId = ref<string | null>(null)
  const folders = ref<FolderResponse[]>([])

  function addUserMessage(content: string): string {
    const id = crypto.randomUUID()
    messages.value.push({ id, role: 'user', content })
    return id
  }

  function addStreamingMessage(): string {
    const id = crypto.randomUUID()
    messages.value.push({ id, role: 'assistant', content: '', isStreaming: true, streamContent: '', streamSql: undefined })
    return id
  }

  function appendStreamToken(id: string, token: string) {
    const msg = messages.value.find((m) => m.id === id)
    if (msg) {
      msg.streamContent = (msg.streamContent ?? '') + token
      msg.content = msg.streamContent
      // Append text to streamEvents timeline (interleaved display)
      const events = msg.streamEvents ?? []
      const last = events[events.length - 1]
      if (last && last.type === 'text' && last.text !== undefined) {
        last.text += token  // Append to existing text block
      } else {
        events.push({ type: 'text', timestamp: Date.now(), text: token })
      }
      msg.streamEvents = events
    }
  }

  function setStreamSql(id: string, sql: string) {
    const msg = messages.value.find((m) => m.id === id)
    if (msg) {
      msg.streamSql = sql
      msg.sql = sql
    }
  }

  function setStreamSources(id: string, sources: string) {
    const msg = messages.value.find((m) => m.id === id)
    if (msg) {
      msg.sources = sources
    }
  }

  function syncMessageIdsFromStream(localAssistantId: string, ids: { user_message_id: string; assistant_message_id: string }) {
    // 从 SSE 流中直接获取服务端消息 ID，替换本地 UUID
    const asstMsg = messages.value.find((m) => m.id === localAssistantId)
    if (asstMsg) {
      asstMsg.id = ids.assistant_message_id
    }
    // 同步最近一条 user 消息的 ID
    for (let i = messages.value.length - 1; i >= 0; i--) {
      const m = messages.value[i]
      if (m && m.role === 'user') {
        m.id = ids.user_message_id
        break
      }
    }
  }

  function setStreamQueryResult(id: string, result: QueryResult) {
    const msg = messages.value.find((m) => m.id === id)
    if (msg) {
      msg.queryResult = result
    }
  }

  function setStreamChartConfig(id: string, config: ChartConfig) {
    const msg = messages.value.find((m) => m.id === id)
    if (msg) {
      msg.chartConfig = config
    }
  }

  function finalizeStreamMessage(id: string, conversationId: string) {
    const msg = messages.value.find((m) => m.id === id)
    if (msg) {
      msg.isStreaming = false
      // Persist streamEvents to localStorage so they survive conversation switches
      if (msg.streamEvents && msg.streamEvents.length > 0) {
        try {
          localStorage.setItem(`stream_events:${id}`, JSON.stringify(msg.streamEvents))
        } catch { /* storage full — ignore */ }
      }
    }
    currentConversationId.value = conversationId
  }

  function _restoreStreamEvents(msg: Message): Message {
    try {
      const raw = localStorage.getItem(`stream_events:${msg.id}`)
      if (raw) {
        msg.streamEvents = JSON.parse(raw)
      }
    } catch { /* ignore parse errors */ }
    return msg
  }

  async function loadConversations(folderId?: string | null) {
    try {
      const params: Record<string, string> = {}
      if (folderId !== undefined) {
        params.folder_id = folderId ?? ''
      }
      conversations.value = await listConversations(Object.keys(params).length ? params : undefined)
    } catch {
      // ignore
    }
  }

  async function loadConversation(id: string) {
    isLoading.value = true
    try {
      const [conv, summary] = await Promise.all([
        getConversation(id),
        getConversationSummary(id).catch(() => null),
      ])
      currentConversationId.value = id
      messages.value = conv.messages.map((m) => {
        const msg: Message = {
          id: m.id,
          role: m.role as 'user' | 'assistant',
          content: m.content,
          sql: m.sql_generated,
          messageType: m.message_type,
          queryResult: m.query_result as QueryResult | null,
          chartConfig: m.chart_config as ChartConfig | null,
        }
        return _restoreStreamEvents(msg)
      })
      conversationSummary.value = summary
    } finally {
      isLoading.value = false
    }
  }

  /**
   * 流式结束后用后端返回的 ID 替换本地 UUID。
   * 按位置匹配（最后一条 user ↔ 最后一条 user，最后一条 assistant ↔ 最后一条 assistant），
   * 不覆盖 content/sql/sources/queryResult 等流式过程中已填充的字段。
   * 返回更新后的 assistant ID（用于后续 finalizeStreamMessage）。
   */
  async function syncMessageIds(conversationId: string) {
    try {
      const conv = await getConversation(conversationId)
      const serverMsgs = conv.messages
      // 从后往前取本地的 user 和 assistant 消息（即本轮对话的两条消息）
      let localUserIdx = -1
      let localAssistantIdx = -1
      for (let i = messages.value.length - 1; i >= 0; i--) {
        const m = messages.value[i]
        if (m && m.role === 'assistant' && localAssistantIdx < 0) localAssistantIdx = i
        else if (m && m.role === 'user' && localUserIdx < 0) { localUserIdx = i; break }
      }
      // 从后往前取服务器的 user 和 assistant 消息
      let svrUserId: string | null = null
      let svrAssistantId: string | null = null
      for (let i = serverMsgs.length - 1; i >= 0; i--) {
        const m = serverMsgs[i]
        if (m && m.role === 'assistant' && !svrAssistantId) svrAssistantId = m.id
        else if (m && m.role === 'user' && !svrUserId) { svrUserId = m.id; break }
      }
      if (localUserIdx >= 0 && svrUserId) {
        messages.value[localUserIdx]!.id = svrUserId
      }
      if (localAssistantIdx >= 0 && svrAssistantId) {
        messages.value[localAssistantIdx]!.id = svrAssistantId
      }
      return svrAssistantId
    } catch {
      return null
    }
  }

  function newConversation() {
    currentConversationId.value = null
    messages.value = []
    conversationSummary.value = null
  }

  async function renameConv(id: string, title: string) {
    await updateConversation(id, { title })
    const conv = conversations.value.find((c) => c.id === id)
    if (conv) conv.title = title
  }

  async function archiveConv(id: string, archived: boolean) {
    await updateConversation(id, { archived })
    const conv = conversations.value.find((c) => c.id === id)
    if (conv) conv.archived = archived
    await loadConversations()
    if (currentConversationId.value === id && archived) {
      newConversation()
    }
  }

  async function moveConvToFolder(convId: string, folderId: string | null) {
    await updateConversation(convId, { folder_id: folderId })
    await loadConversations()
  }

  async function setConvTags(id: string, tags: string[]) {
    await updateConversation(id, { tags })
    const conv = conversations.value.find((c) => c.id === id)
    if (conv) conv.tags = tags
  }

  async function deleteConv(id: string) {
    await deleteConversation(id)
    conversations.value = conversations.value.filter((c) => c.id !== id)
    if (currentConversationId.value === id) {
      currentConversationId.value = null
      messages.value = []
    }
  }

  // ── 文件夹操作 ──

  async function loadFolders() {
    try {
      folders.value = await listFolders()
    } catch {
      // ignore
    }
  }

  async function addFolder(name: string) {
    const folder = await createFolder(name)
    folders.value.unshift(folder)
    return folder
  }

  async function renameFolder(id: string, name: string) {
    await updateFolder(id, name)
    const f = folders.value.find(f => f.id === id)
    if (f) f.name = name
  }

  async function removeFolder(id: string) {
    await deleteFolder(id)
    folders.value = folders.value.filter(f => f.id !== id)
    await loadConversations()
  }

  // ── 批量操作 ──

  async function batchOperate(ids: string[], action: 'archive' | 'delete' | 'move', folderId?: string) {
    await batchOperateConversations(ids, action, folderId)
    await Promise.all([loadConversations(), loadFolders()])
    if (action === 'delete' && currentConversationId.value && ids.includes(currentConversationId.value)) {
      newConversation()
    }
  }

  // ── ReAct streaming observability ──

  function appendThinkingToken(id: string, token: string) {
    const msg = messages.value.find((m) => m.id === id)
    if (msg) {
      const events = msg.streamEvents ?? []
      const last = events[events.length - 1]
      if (last && last.type === 'thinking' && last.thinking !== undefined) {
        last.thinking += token  // Append to existing thinking block
      } else {
        events.push({ type: 'thinking', timestamp: Date.now(), thinking: token })
      }
      msg.streamEvents = events
    }
  }

  function addToolCall(id: string, tc: ToolCallEntry) {
    const msg = messages.value.find((m) => m.id === id)
    if (msg) {
      const events = msg.streamEvents ?? []
      events.push({ type: 'tool_call', timestamp: Date.now(), toolCall: tc })
      msg.streamEvents = events
    }
  }

  function updateToolCallStatus(id: string, name: string, status: 'done' | 'error', result?: string, error?: string) {
    const msg = messages.value.find((m) => m.id === id)
    if (!msg?.streamEvents) return

    const index = msg.streamEvents.findIndex(
      event => event.type === 'tool_call' && event.toolCall?.name === name && event.toolCall.status === 'running',
    )
    if (index < 0) return

    const events = [...msg.streamEvents]
    const current = events[index]
    if (current?.toolCall) {
      events[index] = { ...current, toolCall: { ...current.toolCall, status, result, error } }
      msg.streamEvents = events
    }
  }

  return {
    conversations,
    currentConversationId,
    messages,
    isLoading,
    conversationSummary,
    activeFolderId,
    folders,
    addUserMessage,
    addStreamingMessage,
    appendStreamToken,
    setStreamSql,
    setStreamSources,
    setStreamQueryResult,
    setStreamChartConfig,
    syncMessageIdsFromStream,
    finalizeStreamMessage,
    loadConversations,
    loadConversation,
    syncMessageIds,
    newConversation,
    renameConv,
    archiveConv,
    moveConvToFolder,
    setConvTags,
    deleteConv,
    loadFolders,
    addFolder,
    renameFolder,
    removeFolder,
    batchOperate,
    appendThinkingToken,
    addToolCall,
    updateToolCallStatus,
  }
})
