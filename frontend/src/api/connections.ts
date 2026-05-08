import { apiClient } from './client'

export interface ConnectionCreate {
  name: string
  host?: string
  port?: number
  database_name?: string
  username?: string
  password?: string
  driver_type?: string
  description?: string
  schema_ddl?: string
}

export interface ConnectionResponse {
  id: string
  name: string
  host: string | null
  port: number | null
  database_name: string | null
  username: string | null
  driver_type: string
  connection_tested: boolean
  last_synced_at: string | null
  description: string | null
  is_active: boolean
  has_schema: boolean
  created_at: string
}

export interface TestConnectionResponse {
  status: string
  message: string
  driver: string
}

export interface ConnectionStatusItem {
  id: string
  status: string  // "ok" | "error" | "unknown" | "testing"
}

export interface ConnectionStatusResponse {
  connections: ConnectionStatusItem[]
}

export interface SyncSchemaResponse {
  tables: number
  synced_at: string
}

export interface QueryResultResponse {
  columns: string[]
  rows: unknown[][]
  row_count: number
  execution_time_ms: number
  truncated: boolean
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

export interface TableSchemaItem {
  table_name: string
  columns: string[]
  ddl: string
  description: string
}

export async function getSchemaTables(connectionId: string): Promise<TableSchemaItem[]> {
  const { data } = await apiClient.get<TableSchemaItem[]>(`/connections/${connectionId}/schema/tables`)
  return data
}

export async function testConnection(connectionId: string): Promise<TestConnectionResponse> {
  const { data } = await apiClient.post<TestConnectionResponse>(`/connections/${connectionId}/test`)
  return data
}

export async function getConnectionsStatus(): Promise<ConnectionStatusResponse> {
  const { data } = await apiClient.get<ConnectionStatusResponse>('/connections/status')
  return data
}

export async function syncSchema(connectionId: string): Promise<SyncSchemaResponse> {
  const { data } = await apiClient.post<SyncSchemaResponse>(`/connections/${connectionId}/sync-schema`)
  return data
}

export async function executeQuery(connectionId: string, sql: string, maxRows?: number): Promise<QueryResultResponse> {
  const { data } = await apiClient.post<QueryResultResponse>(`/connections/${connectionId}/query`, {
    sql,
    max_rows: maxRows,
  })
  return data
}
