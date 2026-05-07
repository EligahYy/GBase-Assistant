import { apiClient } from './client'

export interface ErrorCodeQuery {
  query: string
  top_k?: number
}

export interface ErrorCodeItem {
  code: string
  category: string
  description: string
  solution: string
  keywords: string[]
  score: number | null
}

export type ErrorCodeMode = 'exact' | 'semantic' | 'keyword' | 'empty'

export interface ErrorCodeResponse {
  query: string
  mode: ErrorCodeMode
  results: ErrorCodeItem[]
}

export async function queryErrorCode(payload: ErrorCodeQuery): Promise<ErrorCodeResponse> {
  const { data } = await apiClient.post<ErrorCodeResponse>('/tools/error-code', payload)
  return data
}
