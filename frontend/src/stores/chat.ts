import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ConversationResponse } from '@/api/chat'
import { listConversations, getConversation, updateConversation, deleteConversation, getConversationSummary, type ConversationSummary } from '@/api/chat'

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
    }
    currentConversationId.value = conversationId
  }

  async function loadConversations() {
    try {
      conversations.value = await listConversations()
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
      messages.value = conv.messages.map((m) => ({
        id: m.id,
        role: m.role as 'user' | 'assistant',
        content: m.content,
        sql: m.sql_generated,
        messageType: m.message_type,
        queryResult: m.query_result as QueryResult | null,
        chartConfig: m.chart_config as ChartConfig | null,
      }))
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

  return {
    conversations,
    currentConversationId,
    messages,
    isLoading,
    conversationSummary,
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
    setConvTags,
    deleteConv,
  }
})
