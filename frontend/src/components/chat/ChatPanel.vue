<script setup lang="ts">
import { ref, computed, nextTick, watch, inject, onMounted, onBeforeUnmount } from 'vue'
import { useMessage } from 'naive-ui'
import {
  SendOutline, ServerOutline, SunnyOutline, MoonOutline,
  StopCircleOutline, BookOutline,
  GridOutline, SettingsOutline, AlertCircleOutline,
  MenuOutline,
} from '@vicons/ionicons5'
import { NIcon } from 'naive-ui'

import MessageBubble from './MessageBubble.vue'
import { useChatStore } from '@/stores/chat'
import { useConnectionStore } from '@/stores/connection'
import { useSSE } from '@/composables/useSSE'
import { createStreamUrl } from '@/api/chat'
import { useTheme } from '@/composables/useTheme'

const chatStore = useChatStore()
const connStore = useConnectionStore()
const naiveMsg = useMessage()
const { isStreaming, streamPost, stopStream } = useSSE()
const { theme, toggle: toggleTheme } = useTheme()
const toggleSidebar = inject<() => void>('toggleSidebar', () => {})

const inputText = ref('')
const isComposing = ref(false)
const messagesContainer = ref<HTMLElement | null>(null)
const selectedModel = ref(localStorage.getItem('gbase_model') || 'deepseek/deepseek-chat')
const modelDisplayName = computed(() => {
  const name = selectedModel.value.split('/').pop() || 'DeepSeek'
  return name.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
})

const activeConn = computed(() =>
  connStore.connections.find(c => c.id === connStore.activeConnectionId)
)

onMounted(() => {
  connStore.loadConnections().catch(() => {})
})

// 切换对话时停止当前流，防止旧流继续更新已替换的消息列表
watch(() => chatStore.currentConversationId, (newId, oldId) => {
  if (oldId && newId !== oldId && isStreaming.value) {
    stopStream()
  }
})

onBeforeUnmount(() => {
  if (isStreaming.value) {
    stopStream()
  }
})

watch(() => chatStore.messages.length, async () => {
  await nextTick()
  scrollToBottom()
})

watch(() => chatStore.messages.map(m => m.content).join(''), async () => {
  await nextTick()
  if (messagesContainer.value) {
    const el = messagesContainer.value
    const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 150
    if (isNearBottom) scrollToBottom()
  }
})

function scrollToBottom() {
  if (messagesContainer.value) {
    messagesContainer.value.scrollTo({ top: messagesContainer.value.scrollHeight, behavior: 'smooth' })
  }
}

async function sendMessage() {
  const text = inputText.value.trim()
  if (!text || isStreaming.value) return
  inputText.value = ''
  chatStore.addUserMessage(text)
  const streamingId = chatStore.addStreamingMessage()
  const conversationId = chatStore.currentConversationId
  const { url, body } = createStreamUrl({
    message: text,
    conversation_id: conversationId,
    db_connection_id: connStore.activeConnectionId,
    model: selectedModel.value,
    folder_id: chatStore.activeFolderId,
  })
  const serverConversationId = await streamPost(url, body, (chunk) => {
    if (chunk.type === 'TEXT_MESSAGE_CONTENT') {
      chatStore.appendStreamToken(streamingId, (chunk.delta as string) || '')
    } else if (chunk.type === 'text') {
      chatStore.appendStreamToken(streamingId, chunk.content ?? '')
    } else if (chunk.type === 'sql') {
      chatStore.setStreamSql(streamingId, chunk.content ?? '')
    } else if (chunk.type === 'sources') {
      chatStore.setStreamSources(streamingId, chunk.content ?? '')
    } else if (chunk.type === 'result') {
      try {
        const result = JSON.parse(chunk.content ?? '{}')
        chatStore.setStreamQueryResult(streamingId, result)
      } catch {
        // ignore
      }
    } else if (chunk.type === 'error') {
      naiveMsg.error(chunk.content ?? '流式请求失败')
    } else if (chunk.type === 'result_error') {
      naiveMsg.warning(chunk.content ?? '查询结果异常')
    } else if (chunk.type === 'chart_config') {
      try {
        const config = JSON.parse(chunk.content || '{}')
        chatStore.setStreamChartConfig(streamingId, config)
      } catch {
        // ignore
      }
    } else if (chunk.type === 'message_ids') {
      try {
        const ids = JSON.parse(chunk.content ?? '{}')
        chatStore.syncMessageIdsFromStream(streamingId, ids)
      } catch {
        // ignore parse errors
      }
    } else if (chunk.type === 'STATE_DELTA') {
      const path = (chunk as any).path
      const value = (chunk as any).value
      if (path === 'sql') {
        const sql = typeof value === 'string' ? value : value?.sql || ''
        chatStore.setStreamSql(streamingId, sql)
      } else if (path === 'result') {
        chatStore.setStreamQueryResult(streamingId, value)
      } else if (path === 'chart_config') {
        chatStore.setStreamChartConfig(streamingId, value)
      } else if (path === 'sources') {
        chatStore.setStreamSources(streamingId, (value?.sources || []).join('\n'))
      }
    } else if (chunk.type === 'THINKING_CONTENT') {
      chatStore.appendThinkingToken(streamingId, chunk.delta || '')
    } else if (chunk.type === 'TOOL_CALL_START') {
      chatStore.addToolCall(streamingId, {
        id: `${chunk.tool_name}-${Date.now()}`,
        name: chunk.tool_name || 'unknown',
        args: (chunk.args as Record<string, unknown>) || {},
        status: 'running',
        agentName: chunk.agent_name || 'unknown',
      })
    } else if (chunk.type === 'TOOL_CALL_RESULT') {
      const result = chunk.result as any
      chatStore.updateToolCallStatus(
        streamingId,
        chunk.tool_name || 'unknown',
        result?.error ? 'error' : 'done',
        result?.summary,
        result?.error,
      )
    }
  })

  // 流结束后立即从后端同步服务端消息 ID（必须在 finalizeStreamMessage 之前完成）
  let finalAsstId: string | null = streamingId
  if (serverConversationId) {
    const syncedId = await chatStore.syncMessageIds(serverConversationId)
    if (syncedId) finalAsstId = syncedId
  }

  chatStore.finalizeStreamMessage(finalAsstId, serverConversationId ?? conversationId ?? crypto.randomUUID())
  chatStore.activeFolderId = null
  await chatStore.loadConversations()
}

function handleStop() { stopStream() }

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey && !isComposing.value) {
    e.preventDefault()
    sendMessage()
  }
}

</script>

<template>
  <div class="chat-panel">
    <!-- Header -->
    <header class="chat-header">
      <div class="header-left">
        <button class="header-icon-btn" @click="toggleSidebar" title="切换侧边栏">
          <n-icon :component="MenuOutline" size="18" />
        </button>
        <span class="header-title">GBase Copilot</span>
        <span class="header-badge">GBase 8a 专家模式</span>
      </div>
      <div class="header-right">
        <div
          v-if="activeConn"
          class="conn-badge"
          :class="{
            'status-ok': connStore.connStatusMap[activeConn.id] === 'ok',
            'status-error': connStore.connStatusMap[activeConn.id] === 'error',
            'status-testing': connStore.connStatusMap[activeConn.id] === 'testing',
          }"
        >
          <div class="dot" :class="{ pulsing: connStore.connStatusMap[activeConn.id] !== 'error' }" />
          <n-icon :component="ServerOutline" size="12" />
          <span>{{ activeConn.name }}</span>
        </div>
        <div v-else class="conn-badge muted">
          <div class="dot" />
          <n-icon :component="ServerOutline" size="12" />
          <span>未选择数据库</span>
        </div>
        <span class="model-label" :title="selectedModel">{{ modelDisplayName }}</span>
        <button
          class="theme-toggle"
          :title="theme === 'light' ? '切换深色模式' : '切换浅色模式'"
          @click="toggleTheme"
        >
          <n-icon :component="theme === 'light' ? SunnyOutline : MoonOutline" size="18" />
        </button>
      </div>
    </header>

    <!-- Messages -->
    <div ref="messagesContainer" class="messages">
      <!-- Empty state -->
      <div v-if="chatStore.messages.length === 0" class="empty-state">
        <div class="empty-brand">
          <div class="monogram-wrap">
            <div class="monogram">G</div>
          </div>
          <h2 class="empty-title">今天我能帮你做什么？</h2>
          <p class="empty-sub">GBase 8a MPP 数据库专家助手 — 用自然语言查询数据、优化 SQL、诊断问题</p>
        </div>
        <div class="hint-grid">
          <button class="hint-card" @click="inputText = '查询每个部门薪资最高的 3 名员工'">
            <n-icon :component="GridOutline" size="22" />
            <span class="hint-card-title">数据查询</span>
            <span class="hint-card-desc">用自然语言生成并执行 GBase SQL</span>
          </button>
          <button class="hint-card" @click="inputText = '帮我优化这条 SQL 的查询性能'">
            <n-icon :component="SettingsOutline" size="22" />
            <span class="hint-card-title">SQL 优化</span>
            <span class="hint-card-desc">执行计划分析与分布键优化建议</span>
          </button>
          <button class="hint-card" @click="inputText = 'GBase 8a 支持窗口函数吗？'">
            <n-icon :component="BookOutline" size="22" />
            <span class="hint-card-title">知识问答</span>
            <span class="hint-card-desc">基于官方手册回答 GBase 8a 问题</span>
          </button>
          <button class="hint-card" @click="inputText = '错误码 1146 怎么解决？'">
            <n-icon :component="AlertCircleOutline" size="22" />
            <span class="hint-card-title">错误诊断</span>
            <span class="hint-card-desc">错误码查询与解决方案</span>
          </button>
        </div>
      </div>

      <div v-else class="messages-list">
        <!-- Conversation Summary -->
        <div
          v-if="chatStore.conversationSummary?.has_summary"
          class="summary-card"
        >
          <div class="summary-header">
            <n-icon :component="BookOutline" size="14" />
            <span>对话摘要</span>
          </div>
          <div class="summary-body">{{ chatStore.conversationSummary!.summary }}</div>
          <div v-if="chatStore.conversationSummary!.key_sql" class="summary-sql">
            <code>{{ chatStore.conversationSummary!.key_sql }}</code>
          </div>
          <div v-if="chatStore.conversationSummary!.key_topics?.length" class="summary-topics">
            <span
              v-for="topic in chatStore.conversationSummary!.key_topics"
              :key="topic"
              class="topic-tag"
            >{{ topic }}</span>
          </div>
        </div>
        <MessageBubble
          v-for="msg in chatStore.messages"
          :key="msg.id"
          :message="msg"
        />
      </div>
    </div>

    <!-- Input -->
    <div class="input-area">
      <div class="input-capsule" :class="{ disabled: isStreaming }">
        <n-input
          v-model:value="inputText"
          type="textarea"
          placeholder="输入问题，Enter 发送，Shift+Enter 换行..."
          :autosize="{ minRows: 1, maxRows: 6 }"
          :disabled="isStreaming"
          class="chat-input"
          @keydown="handleKeydown"
          @compositionstart="isComposing = true"
          @compositionend="isComposing = false"
        />
        <button
          v-if="isStreaming"
          class="send-circle stop"
          @click="handleStop"
        >
          <n-icon :component="StopCircleOutline" size="16" />
        </button>
        <button
          v-else
          class="send-circle"
          :class="{ active: inputText.trim() }"
          :disabled="!inputText.trim()"
          @click="sendMessage"
        >
          <n-icon :component="SendOutline" size="16" />
        </button>
      </div>
      <p class="input-hint">GBase Copilot 可能生成不准确的 SQL，请验证后使用</p>
    </div>
  </div>
</template>

<style scoped>
.chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 100%;
  overflow: hidden;
  background: var(--bg-void);
  position: relative;
}

/* ── Header ── */
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: var(--header-height);
  flex-shrink: 0;
  background: var(--bg-void);
  border-bottom: 1px solid var(--seam-1);
  position: relative;
  z-index: 10;
}

.header-left, .header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-brand);
  letter-spacing: -0.01em;
}
.header-badge {
  font-size: 10px;
  color: var(--text-3);
  background: var(--bg-panel);
  padding: 2px 8px;
  border-radius: 5px;
  font-weight: 500;
  border: 1px solid var(--seam-1);
}

.header-icon-btn {
  display: none;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-md);
  color: var(--text-3);
  cursor: pointer;
  transition: all var(--duration-fast);
}
.header-icon-btn:hover {
  border-color: var(--seam-2);
  color: var(--text-1);
}
@media (max-width: 768px) {
  .header-icon-btn { display: flex; }
}

.theme-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-md);
  color: var(--text-3);
  cursor: pointer;
  transition: all var(--duration-fast);
}
.theme-toggle:hover {
  background: var(--bg-hover);
  border-color: var(--seam-2);
  color: var(--text-1);
}

.conn-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-3);
  background: var(--bg-panel);
  padding: 5px 12px;
  border-radius: 100px;
  border: 1px solid var(--seam-1);
  font-family: var(--font-mono);
  transition: all var(--duration-fast);
}
.conn-badge:hover {
  border-color: var(--seam-2);
}
.conn-badge .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-4);
  position: relative;
  transition: background var(--duration-fast);
}
.conn-badge.status-ok .dot {
  background: var(--success);
}
.conn-badge.status-ok .dot.pulsing::after {
  content: '';
  position: absolute;
  inset: -3px;
  border-radius: 50%;
  border: 1px solid rgba(22, 163, 74, 0.3);
  animation: pulseRing 2.5s ease-out infinite;
}
/* 状态：检测中（琥珀色脉冲） */
.conn-badge.status-testing .dot {
  background: var(--warning);
}
.conn-badge.status-testing .dot.pulsing::after {
  content: '';
  position: absolute;
  inset: -3px;
  border-radius: 50%;
  border: 1px solid rgba(217, 119, 6, 0.3);
  animation: pulseRing 2.5s ease-out infinite;
}
.conn-badge.status-error .dot {
  background: var(--error);
}
.conn-badge.muted .dot {
  background: var(--text-4);
}

@keyframes pulseRing {
  0% { transform: scale(1); opacity: 1; }
  100% { transform: scale(2.5); opacity: 0; }
}

.status-checking {
  font-size: 10px;
  color: var(--text-muted);
  margin-left: 4px;
}

.model-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-4);
  background: var(--bg-panel);
  padding: 5px 12px;
  border-radius: 100px;
  border: 1px solid var(--seam-1);
  font-family: var(--font-mono);
}

/* ── Messages ── */
.messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  scroll-behavior: smooth;
}
.messages-list {
  max-width: var(--max-content-width);
  width: 100%;
  margin: 0 auto;
  padding: 28px 28px 180px;
}
@media (max-width: 1024px) {
  .messages-list { max-width: 100%; padding: 24px 24px 180px; }
}
@media (max-width: 768px) {
  .messages-list { padding: 16px 16px 180px; }
  .chat-header { padding: 0 16px; }
}

/* ── Summary Card ── */
.summary-card {
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-lg);
  padding: 14px 16px;
  margin-bottom: 16px;
  max-width: var(--max-content-width);
  width: 100%;
}
.summary-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-4);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  margin-bottom: 8px;
}
.summary-body {
  font-size: 13px;
  color: var(--text-1);
  line-height: 1.6;
  margin-bottom: 8px;
}
.summary-sql {
  background: var(--bg-deep);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-sm);
  padding: 8px 12px;
  margin-bottom: 8px;
  overflow-x: auto;
}
.summary-sql code {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-0);
  white-space: pre-wrap;
  word-break: break-word;
}
.summary-topics {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.topic-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--bg-deep);
  color: var(--text-2);
  border: 1px solid var(--seam-1);
}

/* ── Empty State ── */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: calc(100vh - var(--header-height) - 200px);
  padding: 40px 20px;
  text-align: center;
  animation: fadeIn 0.5s var(--ease-out-expo) both;
}
.empty-brand {
  margin-bottom: 36px;
}
.monogram-wrap {
  position: relative;
  width: 72px;
  height: 72px;
  margin: 0 auto 24px;
  animation: fadeInUp 0.4s 0.1s var(--ease-out-expo) both;
}
.monogram {
  width: 72px;
  height: 72px;
  background: var(--text-0);
  color: var(--bg-void);
  border-radius: 18px;
  font-size: 34px;
  font-weight: 800;
  font-family: var(--font-sans);
  display: flex;
  align-items: center;
  justify-content: center;
  letter-spacing: -2px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}
.empty-title {
  font-size: 28px;
  font-weight: 700;
  color: var(--text-0);
  letter-spacing: -0.03em;
  margin-bottom: 10px;
  animation: fadeInUp 0.4s 0.2s var(--ease-out-expo) both;
}
.empty-sub {
  font-size: 14px;
  color: var(--text-3);
  line-height: 1.6;
  max-width: 360px;
  animation: fadeInUp 0.4s 0.25s var(--ease-out-expo) both;
}

.hint-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  max-width: 520px;
  width: 100%;
  animation: fadeInUp 0.4s 0.3s var(--ease-out-expo) both;
}
@media (max-width: 640px) {
  .hint-grid { grid-template-columns: 1fr; }
}
.hint-card {
  padding: 18px 20px;
  background: var(--bg-header);
  border: 1px solid var(--seam-1);
  border-radius: 14px;
  text-align: left;
  cursor: pointer;
  font-family: var(--font-sans);
  transition: all 0.15s ease;
  box-shadow: 0 1px 3px rgba(0,0,0,0.03);
  display: flex;
  flex-direction: column;
  gap: 6px;
  line-height: 1.3;
}
.hint-card:hover {
  border-color: var(--seam-2);
  box-shadow: 0 4px 16px rgba(0,0,0,0.06);
}
.hint-card .n-icon {
  color: var(--text-2);
}
.hint-card-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-brand);
}
.hint-card-desc {
  font-size: 11px;
  color: var(--text-3);
}

/* ── Input ── */
.input-area {
  flex-shrink: 0;
  padding: 24px 28px 28px;
  position: relative;
  z-index: 20;
  background: var(--bg-void);
  pointer-events: none;
}
.input-area > * {
  pointer-events: auto;
}
.input-capsule {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  max-width: 720px;
  width: 100%;
  margin: 0 auto;
  background: var(--bg-surface);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-xl);
  padding: 14px 16px 14px 22px;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.06), 0 1px 3px rgba(0, 0, 0, 0.04), 0 0 0 1px rgba(0, 0, 0, 0.02);
  transition: all var(--duration-fast) var(--ease-smooth);
}
.input-capsule:focus-within {
  border-color: var(--seam-2);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.08), 0 2px 6px rgba(0, 0, 0, 0.04), 0 0 0 1px rgba(0, 0, 0, 0.03);
}
.input-capsule.disabled {
  opacity: 0.7;
}

.chat-input {
  flex: 1;
}
:deep(.n-input) {
  --n-border: none !important;
  --n-border-hover: none !important;
  --n-border-focus: none !important;
  --n-box-shadow-focus: none !important;
  background: transparent !important;
}
:deep(.n-input__border),
:deep(.n-input__state-border) {
  display: none !important;
}
:deep(.n-input-wrapper) {
  padding: 0 !important;
  background: transparent !important;
}

.send-circle {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: none;
  background: var(--bg-edge);
  color: var(--text-4);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
  transition: all var(--duration-fast);
  margin-bottom: 2px;
}
.send-circle.active {
  background: var(--text-0);
  color: var(--bg-void);
}
.send-circle.active:hover {
  background: var(--text-1);
  transform: scale(1.05);
}
.send-circle:disabled {
  cursor: not-allowed;
}
.send-circle.stop {
  background: var(--error);
  color: #fff;
}
.send-circle.stop:hover {
  background: #b91c1c;
  transform: scale(1.05);
}

.input-hint {
  text-align: center;
  font-size: 11px;
  color: var(--text-4);
  margin-top: 10px;
  letter-spacing: 0.01em;
  font-family: var(--font-mono);
}
</style>
