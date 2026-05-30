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

export interface StatusStreamEvent {
  type: 'status' | 'heartbeat' | 'closed'
  connection_id?: string
  status?: string
}

export function connectStatusStream(
  baseUrl: string,
  onEvent: (event: StatusStreamEvent) => void,
  onError?: (err: Error) => void,
): AbortController {
  const controller = new AbortController()
  const url = `${baseUrl}/connections/status/stream`

  void (async () => {
    try {
      const response = await fetch(url, {
        signal: controller.signal,
        headers: { Accept: 'text/event-stream' },
      })

      if (!response.ok) {
        throw new Error(`SSE connect failed: HTTP ${response.status}`)
      }

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6).trim()
            if (!data) continue
            try {
              const event = JSON.parse(data) as StatusStreamEvent
              onEvent(event)
            } catch { /* ignore malformed */ }
          }
          // ": keepalive" lines are ignored
        }
      }
      // Stream ended normally (server closed connection)
      onError?.(new Error('SSE stream ended'))
    } catch (e: any) {
      if (e.name !== 'AbortError') {
        onError?.(e instanceof Error ? e : new Error(String(e)))
      }
    }
  })()

  return controller
}
