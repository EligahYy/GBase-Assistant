<script setup lang="ts">
import { ref, computed, nextTick, watch, inject, onMounted, onBeforeUnmount } from 'vue'
import { useMessage } from 'naive-ui'
import {
  SendOutline, ServerOutline, SunnyOutline, MoonOutline,
  StopCircleOutline, BookOutline, SparklesOutline,
} from '@vicons/ionicons5'
import { NIcon } from 'naive-ui'

import MessageBubble from './MessageBubble.vue'
import { useChatStore } from '@/stores/chat'
import { useConnectionStore } from '@/stores/connection'
import { useSSE } from '@/composables/useSSE'
import { createStreamUrl } from '@/api/chat'
import { getConnectionsStatus } from '@/api/connections'
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

// ── 连接状态实时检测 ──
const connStatusMap = ref<Record<string, 'ok' | 'error' | 'testing'>>({})
const connStatusLoading = ref(false)
const POLL_INTERVAL = 5000

async function checkConnectionStatus() {
  connStatusLoading.value = true
  try {
    const resp = await getConnectionsStatus()
    for (const item of resp.connections) {
      if (item.status === 'ok') {
        connStatusMap.value[item.id] = 'ok'
      } else if (item.status === 'testing') {
        connStatusMap.value[item.id] = 'testing'
      } else {
        connStatusMap.value[item.id] = 'error'
      }
    }
  } catch {
    // ignore
  } finally {
    connStatusLoading.value = false
  }
}

let pollTimer: ReturnType<typeof setInterval> | null = null

function startPolling() {
  checkConnectionStatus()
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(checkConnectionStatus, POLL_INTERVAL)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function handleVisibilityChange() {
  if (document.visibilityState === 'visible') {
    checkConnectionStatus()
  }
}

onMounted(() => {
  connStore.loadConnections().catch(() => {})
  startPolling()
  document.addEventListener('visibilitychange', handleVisibilityChange)
})

onBeforeUnmount(() => {
  stopPolling()
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})

watch(() => connStore.activeConnectionId, () => {
  startPolling()
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
  })
  const serverConversationId = await streamPost(url, body, (chunk) => {
    if (chunk.type === 'text') {
      chatStore.appendStreamToken(streamingId, chunk.content)
    } else if (chunk.type === 'sql') {
      chatStore.setStreamSql(streamingId, chunk.content)
    } else if (chunk.type === 'sources') {
      chatStore.setStreamSources(streamingId, chunk.content)
    } else if (chunk.type === 'result') {
      try {
        const result = JSON.parse(chunk.content)
        chatStore.setStreamQueryResult(streamingId, result)
      } catch {
        // ignore
      }
    } else if (chunk.type === 'error') {
      naiveMsg.error(chunk.content)
    } else if (chunk.type === 'result_error') {
      naiveMsg.warning(chunk.content)
    } else if (chunk.type === 'message_ids') {
      try {
        const ids = JSON.parse(chunk.content)
        chatStore.syncMessageIdsFromStream(streamingId, ids)
      } catch {
        // ignore parse errors
      }
    }
  })

  // 流结束后立即从后端同步服务端消息 ID（必须在 finalizeStreamMessage 之前完成）
  let finalAsstId: string | null = streamingId
  if (serverConversationId) {
    const syncedId = await chatStore.syncMessageIds(serverConversationId)
    if (syncedId) finalAsstId = syncedId
  }

  chatStore.finalizeStreamMessage(finalAsstId, serverConversationId ?? conversationId ?? crypto.randomUUID())
  await chatStore.loadConversations()
}

function handleStop() { stopStream() }

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey && !isComposing.value) {
    e.preventDefault()
    sendMessage()
  }
}

const hints = [
  '查询每个部门薪资最高的 3 名员工',
  '统计最近 30 天每天的订单数和总金额',
  'GBase 8a 支持窗口函数吗？',
  '如何建表并指定分布键？',
]
</script>

<template>
  <div class="chat-panel">
    <!-- Header -->
    <header class="chat-header">
      <div class="header-left">
        <button class="header-icon-btn" @click="toggleSidebar">
          <n-icon :component="SparklesOutline" size="18" />
        </button>
        <div
          v-if="activeConn"
          class="conn-badge"
          :class="{
            'status-ok': connStatusMap[activeConn.id] === 'ok',
            'status-error': connStatusMap[activeConn.id] === 'error',
            'status-testing': connStatusMap[activeConn.id] === 'testing',
          }"
        >
          <div class="dot" :class="{ pulsing: connStatusMap[activeConn.id] !== 'error' }" />
          <n-icon :component="ServerOutline" size="12" />
          <span>{{ activeConn.name }}</span>
          <span v-if="connStatusMap[activeConn.id] === 'testing'" class="status-checking">检测中</span>
        </div>
        <div v-else class="conn-badge muted">
          <div class="dot" />
          <n-icon :component="ServerOutline" size="12" />
          <span>未选择数据库</span>
        </div>
      </div>
      <div class="header-right">
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
          <h2 class="empty-title">GBase 助手</h2>
          <p class="empty-sub">输入自然语言查询，自动生成 SQL 并执行</p>
        </div>
        <div class="hint-grid">
          <button
            v-for="hint in hints"
            :key="hint"
            class="hint-card"
            @click="inputText = hint"
          >
            {{ hint }}
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
      <p class="input-hint">GBase 助手可能生成不准确的 SQL，请验证后使用</p>
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
  margin-bottom: 32px;
}
.monogram-wrap {
  position: relative;
  width: 64px;
  height: 64px;
  margin: 0 auto 24px;
  animation: fadeInUp 0.4s 0.1s var(--ease-out-expo) both;
}
.monogram {
  width: 64px;
  height: 64px;
  background: var(--text-0);
  color: var(--bg-void);
  border-radius: var(--radius-lg);
  font-size: 24px;
  font-weight: 700;
  font-family: var(--font-mono);
  display: flex;
  align-items: center;
  justify-content: center;
}
.empty-title {
  font-size: 24px;
  font-weight: 600;
  color: var(--text-0);
  letter-spacing: -0.02em;
  margin-bottom: 8px;
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
  gap: 10px;
  max-width: 480px;
  width: 100%;
  animation: fadeInUp 0.4s 0.3s var(--ease-out-expo) both;
}
@media (max-width: 640px) {
  .hint-grid { grid-template-columns: 1fr; }
}
.hint-card {
  padding: 14px 16px;
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-lg);
  font-size: 13px;
  color: var(--text-2);
  text-align: left;
  cursor: pointer;
  font-family: var(--font-sans);
  font-weight: 500;
  transition: all var(--duration-fast);
  line-height: 1.5;
}
.hint-card:hover {
  background: var(--bg-raised);
  border-color: var(--seam-2);
  color: var(--text-0);
}

/* ── Input ── */
.input-area {
  flex-shrink: 0;
  padding: 24px 28px 28px;
  position: relative;
  z-index: 20;
  background: linear-gradient(to top, var(--bg-void) 60%, transparent 100%);
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
