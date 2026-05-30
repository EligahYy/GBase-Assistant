import { ref } from 'vue'

export interface SSEChunk {
  type: 'text' | 'sql' | 'sources' | 'warning' | 'done' | 'error' | 'result' | 'result_error' | 'message_ids' | 'TEXT_MESSAGE_CONTENT' | 'chart_config' | 'STATE_DELTA'
  content?: string
  delta?: string
  path?: string
  value?: any
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

    // 文本 chunk 缓冲：累积短 token 批量触发，减少前端渲染频率
    let textBuffer = ''
    let flushTimer: ReturnType<typeof setTimeout> | null = null

    function flushTextBuffer() {
      if (textBuffer) {
        onChunk({ type: 'text', content: textBuffer })
        textBuffer = ''
      }
      if (flushTimer) {
        clearTimeout(flushTimer)
        flushTimer = null
      }
    }

    function scheduleFlush() {
      if (flushTimer) return
      flushTimer = setTimeout(() => {
        flushTextBuffer()
      }, 60)
    }

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
              if (chunk.type === 'TEXT_MESSAGE_CONTENT') {
                textBuffer += chunk.delta || ''
                scheduleFlush()
              } else if (chunk.type === 'text') {
                textBuffer += chunk.content || ''
                scheduleFlush()
              } else {
                flushTextBuffer() // 非 text chunk 前立即刷新缓冲区
                onChunk(chunk)
              }
            } catch {
              // ignore malformed chunks
            }
          }
        }
      }
      flushTextBuffer() // 确保尾部文本被刷新
      return conversationId
    } catch (e: any) {
      flushTextBuffer()
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
