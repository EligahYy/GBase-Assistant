import { apiClient } from './client'

export interface HealthStatus {
  status: string          // "ok" | "degraded"
  dependencies: {
    database: string      // "connected" | "disconnected" | "unknown"
    llm_api: string       // "connected" | "unreachable" | "unknown"
    vector_db: string     // "connected" | "degraded" | "disconnected" | "unknown"
    default_model: string // model name string
    gbase_connections: string  // "connected" | "disconnected" | "partial" | "untested" | "no_connections" | "unknown"
  }
}

export interface ReindexResponse {
  status: string
  results: Record<string, number>
}

export async function getHealthStatus(): Promise<HealthStatus> {
  const { data } = await apiClient.get<HealthStatus>('/health')
  return data
}

export async function triggerReindex(token: string): Promise<ReindexResponse> {
  const { data } = await apiClient.post<ReindexResponse>('/admin/reindex', {}, {
    headers: { 'X-Admin-Token': token },
  })
  return data
}

export interface FeedbackStats {
  total: number
  accepted: number
  rejected: number
  modified: number
  enriched: number
  pending: number
}

export async function getFeedbackStats(token: string): Promise<FeedbackStats> {
  const { data } = await apiClient.get<FeedbackStats>('/admin/feedback-stats', {
    headers: { 'X-Admin-Token': token },
  })
  return data
}

export async function triggerEnrichFeedback(token: string): Promise<{ added: number; skipped: number; failed: number }> {
  const { data } = await apiClient.post('/admin/enrich-feedback', {}, {
    headers: { 'X-Admin-Token': token },
  })
  return data
}
