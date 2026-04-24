import { apiClient } from './client'

export interface FeedbackRequest {
  message_id: string
  action: 'accepted' | 'rejected' | 'modified'
  modified_sql?: string
  feedback_note?: string
}

export async function submitFeedback(request: FeedbackRequest): Promise<void> {
  await apiClient.post('/chat/feedback', request)
}
