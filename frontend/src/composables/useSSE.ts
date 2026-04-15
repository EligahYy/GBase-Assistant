import { ref } from 'vue'

export interface SSEChunk {
  type: 'text' | 'sql' | 'sources' | 'warning' | 'done' | 'error'
  content: string
  token_usage?: Record<string, unknown>
}

export function useSSE() {
  const isStreaming = ref(false)
  const error = ref<string | null>(null)
  let abortController: AbortController | null = null

  async function streamPost(
    url: string,
    body: string,
    onChunk: (chunk: SSEChunk) => void,
  ): Promise<string | null> {
    isStreaming.value = true
    error.value = null
    abortController = new AbortController()

    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        body,
        signal: abortController.signal,
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      const conversationId = response.headers.get('x-conversation-id')
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
            if (!data || data === '[DONE]') continue
            try {
              const chunk = JSON.parse(data) as SSEChunk
              onChunk(chunk)
            } catch {
              // ignore malformed chunks
            }
          }
        }
      }
      return conversationId
    } catch (e: any) {
      if (e.name === 'AbortError') {
        error.value = '已停止生成'
        onChunk({ type: 'error', content: '已停止生成' })
        return null
      }
      error.value = e instanceof Error ? e.message : '流式请求失败'
      onChunk({ type: 'error', content: error.value })
      return null
    } finally {
      isStreaming.value = false
      abortController = null
    }
  }

  function stopStream() {
    abortController?.abort()
  }

  return { isStreaming, error, streamPost, stopStream }
}
