import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ConversationResponse, MessageResponse } from '@/api/chat'
import { listConversations, getConversation, updateConversation, deleteConversation } from '@/api/chat'

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  sql?: string | null
  messageType?: string | null
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

  function finalizeStreamMessage(id: string, conversationId: string) {
    const msg = messages.value.find((m) => m.id === id)
    if (msg) {
      msg.isStreaming = false
    }
    currentConversationId.value = conversationId
  }

  function addAssistantMessage(response: MessageResponse, conversationId: string) {
    messages.value.push({
      id: response.id,
      role: 'assistant',
      content: response.content,
      sql: response.sql_generated,
      messageType: response.message_type,
    })
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
      const conv = await getConversation(id)
      currentConversationId.value = id
      messages.value = conv.messages.map((m) => ({
        id: m.id,
        role: m.role as 'user' | 'assistant',
        content: m.content,
        sql: m.sql_generated,
        messageType: m.message_type,
      }))
    } finally {
      isLoading.value = false
    }
  }

  function newConversation() {
    currentConversationId.value = null
    messages.value = []
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
    addUserMessage,
    addStreamingMessage,
    appendStreamToken,
    setStreamSql,
    finalizeStreamMessage,
    addAssistantMessage,
    loadConversations,
    loadConversation,
    newConversation,
    renameConv,
    archiveConv,
    setConvTags,
    deleteConv,
  }
})
