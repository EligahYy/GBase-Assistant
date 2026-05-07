import { apiClient } from './client'

export interface HealthStatus {
  status: string
  dependencies: {
    database: string
    llm_api: string
    vector_db: string
    default_model: string
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
