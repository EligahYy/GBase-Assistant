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
  created_at: string
  messages: MessageResponse[]
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

export async function listConversations(): Promise<ConversationResponse[]> {
  const { data } = await apiClient.get<ConversationResponse[]>('/chat/conversations')
  return data
}

export async function getConversation(id: string): Promise<ConversationResponse> {
  const { data } = await apiClient.get<ConversationResponse>(`/chat/conversations/${id}`)
  return data
}

export async function updateConversation(
  id: string,
  payload: { title?: string; archived?: boolean; tags?: string[] }
): Promise<void> {
  await apiClient.patch(`/chat/conversations/${id}`, payload)
}

export async function deleteConversation(id: string): Promise<void> {
  await apiClient.delete(`/chat/conversations/${id}`)
}
