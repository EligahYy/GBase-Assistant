import { apiClient } from './client'

export interface KnowledgeDocument {
  id: string
  filename: string
  file_type: string
  file_size: number
  status: 'pending' | 'parsing' | 'chunking' | 'indexing' | 'ready' | 'error'
  chunk_count: number
  error_message: string | null
  created_at: string
  indexed_at: string | null
}

export interface DocumentListResponse {
  documents: KnowledgeDocument[]
  total: number
}

export interface IndexStateResponse {
  total_documents: number
  total_chunks: number
  ready_documents: number
  last_indexed_at: string | null
}

export interface IndexProgressEvent {
  event: 'progress' | 'complete' | 'error' | 'heartbeat'
  data: Record<string, unknown>
}

export async function fetchDocuments(params?: {
  page?: number
  page_size?: number
  file_type?: string
  status?: string
}): Promise<DocumentListResponse> {
  const { data } = await apiClient.get<DocumentListResponse>('/admin/knowledge/documents', { params })
  return data
}

export async function uploadDocument(file: File): Promise<KnowledgeDocument> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await apiClient.post<KnowledgeDocument>('/admin/knowledge/documents/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function deleteDocument(id: string): Promise<void> {
  await apiClient.delete(`/admin/knowledge/documents/${id}`)
}

export async function reindexDocument(id: string): Promise<void> {
  await apiClient.post(`/admin/knowledge/documents/${id}/reindex`)
}

export async function cancelIndexing(id: string): Promise<void> {
  await apiClient.post(`/admin/knowledge/documents/${id}/cancel`)
}

export async function reindexAll(token?: string): Promise<void> {
  await apiClient.post('/admin/knowledge/reindex-all', {}, {
    headers: token ? { 'X-Admin-Token': token } : {},
  })
}

export async function fetchIndexState(): Promise<IndexStateResponse> {
  const { data } = await apiClient.get<IndexStateResponse>('/admin/knowledge/index-state')
  return data
}

export function getProgressSSEUrl(documentId: string): string {
  const base = apiClient.defaults.baseURL || 'http://localhost:8000/api'
  return `${base}/admin/knowledge/documents/${documentId}/index-progress`
}
