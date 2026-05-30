import { apiClient } from './client'

export interface ChatRequest {
  message: string
  conversation_id?: string | null
  db_connection_id?: string | null
  model?: string | null
}

export interface MessageResponse {
  id: string
  role: string
  content: string
  message_type: string | null
  sql_generated: string | null
  sql_validated: boolean | null
  query_result: Record<string, unknown> | null
  chart_config: Record<string, unknown> | null
  token_usage: Record<string, unknown> | null
  created_at: string
}

export interface ChatResponse {
  conversation_id: string
  message: MessageResponse
}

export interface ConversationResponse {
  id: string
  title: string | null
  db_connection_id: string | null
  model_used: string | null
  archived: boolean
  tags: string[]
  folder_id: string | null
  created_at: string
  messages: MessageResponse[]
}

export interface FolderResponse {
  id: string
  name: string
  conversation_count: number
  created_at: string
  updated_at: string
}

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'

export async function sendChat(request: ChatRequest): Promise<ChatResponse> {
  const { data } = await apiClient.post<ChatResponse>('/chat', request)
  return data
}

export function createStreamUrl(request: ChatRequest): { url: string; body: string } {
  return {
    url: `${BASE_URL}/chat/stream`,
    body: JSON.stringify(request),
  }
}

export async function listConversations(params?: Record<string, string>): Promise<ConversationResponse[]> {
  const query = params ? '?' + new URLSearchParams(params).toString() : ''
  const { data } = await apiClient.get<ConversationResponse[]>(`/chat/conversations${query}`)
  return data
}

export async function getConversation(id: string): Promise<ConversationResponse> {
  const { data } = await apiClient.get<ConversationResponse>(`/chat/conversations/${id}`)
  return data
}

export async function updateConversation(
  id: string,
  payload: { title?: string; archived?: boolean; tags?: string[]; folder_id?: string | null }
): Promise<void> {
  await apiClient.patch(`/chat/conversations/${id}`, payload)
}

export async function deleteConversation(id: string): Promise<void> {
  await apiClient.delete(`/chat/conversations/${id}`)
}

// --- Folder API ---

export async function listFolders(): Promise<FolderResponse[]> {
  const { data } = await apiClient.get<FolderResponse[]>('/chat/folders')
  return data
}

export async function createFolder(name: string): Promise<FolderResponse> {
  const { data } = await apiClient.post<FolderResponse>('/chat/folders', { name })
  return data
}

export async function updateFolder(id: string, name: string): Promise<void> {
  await apiClient.patch(`/chat/folders/${id}`, { name })
}

export async function deleteFolder(id: string): Promise<void> {
  await apiClient.delete(`/chat/folders/${id}`)
}

// --- Batch Operations ---

export async function batchOperateConversations(
  ids: string[],
  action: 'archive' | 'delete' | 'move',
  folderId?: string
): Promise<{ affected: number }> {
  const { data } = await apiClient.post<{ affected: number }>('/chat/conversations/batch', {
    ids,
    action,
    folder_id: folderId ?? null,
  })
  return data
}

export interface ConversationSummary {
  has_summary: boolean
  summary?: string
  key_sql?: string
  key_topics?: string[]
  created_at?: string
}

export async function getConversationSummary(id: string): Promise<ConversationSummary> {
  const { data } = await apiClient.get<ConversationSummary>(`/chat/conversations/${id}/summary`)
  return data
}
