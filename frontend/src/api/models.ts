import { apiClient } from './client'

export interface ModelInfo {
  id: string
  name: string
  task_type: string
  primary: boolean
}

export async function listModels(): Promise<ModelInfo[]> {
  const { data } = await apiClient.get<ModelInfo[]>('/models')
  return data
}
