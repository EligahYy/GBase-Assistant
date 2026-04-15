import { apiClient } from './client'

export interface ConnectionCreate {
  name: string
  host?: string
  port?: number
  database_name?: string
  description?: string
  schema_ddl?: string
}

export interface ConnectionResponse {
  id: string
  name: string
  host: string | null
  port: number | null
  database_name: string | null
  description: string | null
  is_active: boolean
  has_schema: boolean
  created_at: string
}

export async function listConnections(): Promise<ConnectionResponse[]> {
  const { data } = await apiClient.get<ConnectionResponse[]>('/connections')
  return data
}

export async function createConnection(payload: ConnectionCreate): Promise<ConnectionResponse> {
  const { data } = await apiClient.post<ConnectionResponse>('/connections', payload)
  return data
}

export async function updateConnection(id: string, payload: Partial<ConnectionCreate>): Promise<ConnectionResponse> {
  const { data } = await apiClient.patch<ConnectionResponse>(`/connections/${id}`, payload)
  return data
}

export async function deleteConnection(id: string): Promise<void> {
  await apiClient.delete(`/connections/${id}`)
}
