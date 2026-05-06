<script setup lang="ts">
import { ref, nextTick, watch, computed, inject } from 'vue'
import { useMessage } from 'naive-ui'
import { SendOutline, ServerOutline, MenuOutline, SunnyOutline, MoonOutline, StopCircleOutline } from '@vicons/ionicons5'
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
    } else if (chunk.type === 'error') {
      naiveMsg.error(chunk.content)
    }
  })
  chatStore.finalizeStreamMessage(streamingId, serverConversationId ?? conversationId ?? crypto.randomUUID())
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
          <n-icon :component="MenuOutline" size="18" />
        </button>
        <div v-if="activeConn" class="conn-badge">
          <div class="dot" />
          <n-icon :component="ServerOutline" size="12" />
          <span>{{ activeConn.name }}</span>
        </div>
        <div v-else class="conn-badge muted">
          <div class="dot" />
          <n-icon :component="ServerOutline" size="12" />
          <span>未选择数据库</span>
        </div>
      </div>
      <div class="header-right">
        <span class="model-label" :title="selectedModel">{{ modelDisplayName }}</span>
        <button class="theme-toggle" :title="theme === 'light' ? '切换深色模式' : '切换浅色模式'" @click="toggleTheme">
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
            <div class="monogram-glow" />
          </div>
          <h2 class="empty-title">建立连接</h2>
          <p class="empty-sub">输入自然语言查询，GBase 助手将自动生成 SQL 并执行</p>
        </div>
        <div class="hint-grid">
          <button v-for="hint in hints" :key="hint" class="hint-card" @click="inputText = hint">
            {{ hint }}
          </button>
        </div>
      </div>

      <div v-else class="messages-list">
        <MessageBubble v-for="msg in chatStore.messages" :key="msg.id" :message="msg" />
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
        <button v-if="isStreaming" class="send-circle stop" @click="handleStop">
          <n-icon :component="StopCircleOutline" size="16" />
        </button>
        <button v-else class="send-circle" :class="{ active: inputText.trim() }" :disabled="!inputText.trim()" @click="sendMessage">
          <n-icon :component="SendOutline" size="16" />
        </button>
      </div>
      <div class="quick-chips">
        <button class="quick-chip" @click="inputText = '解释这段 SQL'">解释 SQL</button>
        <button class="quick-chip" @click="inputText = '优化这个查询'">优化查询</button>
        <button class="quick-chip" @click="inputText = '帮我写一个建表语句'">建表语句</button>
        <button class="quick-chip" @click="inputText = 'GBase 8a 支持哪些数据类型'">数据类型</button>
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

/* Header */
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 28px;
  height: var(--header-height);
  flex-shrink: 0;
  background: linear-gradient(180deg, var(--bg-void), transparent);
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
  align-items: center; justify-content: center;
  width: 32px; height: 32px; padding: 0;
  background: var(--bg-panel); border: 1px solid var(--seam-1);
  border-radius: var(--radius-sm);
  color: var(--text-3); cursor: pointer;
  transition: all var(--duration-fast);
}
.header-icon-btn:hover { border-color: var(--seam-2); color: var(--text-1); }
@media (max-width: 768px) { .header-icon-btn { display: flex; } }

.theme-toggle {
  display: flex; align-items: center; justify-content: center;
  width: 32px; height: 32px; padding: 0;
  background: var(--bg-panel); border: 1px solid var(--seam-1);
  border-radius: var(--radius-sm);
  color: var(--text-3); cursor: pointer;
  transition: all var(--duration-fast);
}
.theme-toggle:hover {
  background: var(--bg-surface);
  border-color: var(--accent-bright);
  color: var(--accent);
  box-shadow: 0 0 10px var(--accent-glow);
}

.conn-badge {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px; font-weight: 500;
  color: var(--text-3);
  background: var(--bg-panel);
  padding: 5px 12px;
  border-radius: 100px;
  border: 1px solid var(--seam-1);
  font-family: var(--font-mono);
  transition: all var(--duration-fast);
}
.conn-badge:hover { border-color: var(--seam-2); }
.conn-badge .dot {
  width: 5px; height: 5px; border-radius: 50%;
  background: var(--status);
  box-shadow: 0 0 6px var(--status-dim);
  position: relative;
}
.conn-badge .dot::after {
  content: ''; position: absolute; inset: -2px; border-radius: 50%;
  border: 1px solid rgba(251,191,36,0.3);
  animation: pulseRing 2.5s ease-out infinite;
}
@keyframes pulseRing {
  0% { transform: scale(1); opacity: 1; }
  100% { transform: scale(2.5); opacity: 0; }
}
.conn-badge.muted .dot { background: var(--text-4); box-shadow: none; }
.conn-badge.muted .dot::after { display: none; }

.model-label {
  font-size: 12px; font-weight: 500;
  color: var(--text-4);
  background: var(--bg-panel);
  padding: 5px 12px;
  border-radius: 100px;
  border: 1px solid var(--seam-1);
  font-family: var(--font-mono);
}

/* Messages */
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

/* Empty state */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: calc(100vh - var(--header-height) - 200px);
  padding: 40px 20px;
  text-align: center;
  animation: fadeIn 1s var(--ease-out-expo) both;
}
.empty-brand {
  margin-bottom: 32px;
}
.monogram-wrap {
  position: relative;
  width: 72px; height: 72px;
  margin: 0 auto 28px;
  animation: floatIn 0.8s 0.2s var(--ease-out-expo) both;
}
.monogram {
  width: 72px; height: 72px;
  background: var(--bg-panel);
  border: 1px solid var(--seam-2);
  color: var(--accent);
  border-radius: 18px;
  font-size: 28px; font-weight: 700;
  font-family: var(--font-mono);
  display: flex; align-items: center; justify-content: center;
  position: relative; z-index: 2;
  box-shadow: 0 0 24px var(--accent-glow);
}
.monogram::after {
  content: ''; position: absolute; inset: 0; border-radius: 18px;
  background: linear-gradient(135deg, transparent 40%, rgba(255,255,255,0.1) 100%);
}
.monogram-glow {
  position: absolute;
  inset: -12px;
  background: radial-gradient(ellipse 60% 50% at 50% 50%, var(--accent-bright), transparent 70%);
  border-radius: 28px;
  animation: breathe 4s ease-in-out infinite;
  z-index: 1;
}
.empty-title {
  font-size: 26px;
  font-weight: 600;
  color: var(--text-0);
  letter-spacing: -0.03em;
  margin-bottom: 10px;
  animation: fadeInUp 0.6s 0.4s var(--ease-out-expo) both;
}
.empty-sub {
  font-size: 15px;
  color: var(--text-3);
  line-height: 1.6;
  max-width: 360px;
  animation: fadeInUp 0.6s 0.5s var(--ease-out-expo) both;
}

.hint-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  max-width: 480px;
  width: 100%;
  animation: fadeInUp 0.6s 0.6s var(--ease-out-expo) both;
}
@media (max-width: 640px) {
  .hint-grid { grid-template-columns: 1fr; }
}
.hint-card {
  position: relative;
  padding: 16px 18px;
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-md);
  font-size: 13px;
  color: var(--text-3);
  text-align: left;
  cursor: pointer;
  font-family: var(--font-sans);
  font-weight: 500;
  transition: all var(--duration-normal) var(--ease-out-expo);
  line-height: 1.5;
  overflow: hidden;
}
.hint-card::before {
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px;
  background: linear-gradient(90deg, transparent, var(--accent-dim), transparent);
  opacity: 0; transition: opacity var(--duration-fast);
}
.hint-card:hover {
  background: var(--bg-surface);
  border-color: var(--seam-2);
  color: var(--text-1);
  transform: translateY(-2px);
  box-shadow: 0 8px 32px rgba(0,0,0,0.2);
}
.hint-card:hover::before { opacity: 1; }

/* Input */
.input-area {
  flex-shrink: 0;
  padding: 16px 28px 28px;
  position: relative;
  z-index: 20;
}
.input-area::before {
  content: ''; position: absolute; top: -60px; left: 0; right: 0; height: 60px;
  background: linear-gradient(to top, var(--bg-void), transparent);
  pointer-events: none;
}
.input-capsule {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  max-width: 680px;
  width: 100%;
  margin: 0 auto;
  background: var(--bg-panel);
  border: 1px solid var(--seam-2);
  border-radius: var(--radius-lg);
  padding: 12px 14px 12px 20px;
  box-shadow: 0 4px 20px rgba(0,0,0,0.2);
  transition: all var(--duration-normal) var(--ease-out-expo);
  position: relative;
}
.input-capsule:focus-within {
  border-color: var(--seam-3);
  box-shadow: 0 4px 24px rgba(0,0,0,0.3), 0 0 0 1px var(--accent-dim);
}
.input-capsule.disabled { opacity: 0.7; }

.chat-input { flex: 1; }
:deep(.n-input) {
  --n-border: none !important;
  --n-border-hover: none !important;
  --n-border-focus: none !important;
  --n-box-shadow-focus: none !important;
  background: transparent !important;
}
:deep(.n-input__border),
:deep(.n-input__state-border) { display: none !important; }
:deep(.n-input-wrapper) { padding: 0 !important; background: transparent !important; }

.send-circle {
  width: 32px; height: 32px;
  border-radius: 50%;
  border: none;
  background: var(--bg-edge);
  color: var(--text-4);
  display: flex;
  align-items: center; justify-content: center;
  cursor: pointer; flex-shrink: 0;
  transition: all var(--duration-fast) var(--ease-spring);
  margin-bottom: 2px;
}
.send-circle.active {
  background: var(--accent-dim);
  color: var(--accent);
  border: 1px solid var(--seam-2);
}
.send-circle.active:hover {
  background: var(--accent-dim); color: var(--accent);
  transform: scale(1.08);
  box-shadow: 0 0 12px var(--accent-glow);
}
.send-circle:disabled { cursor: not-allowed; }
.send-circle.stop {
  background: var(--error);
  color: #fff;
  animation: pulse-ring 1.5s ease-out infinite;
}
.send-circle.stop:hover { background: #ff453a; transform: scale(1.05); }

.input-hint {
  text-align: center;
  font-size: 11px;
  color: var(--text-4);
  margin-top: 10px;
  letter-spacing: 0.02em;
  font-family: var(--font-mono);
}

/* Quick chips */
.quick-chips {
  max-width: 680px;
  margin: 10px auto 0;
  display: flex;
  gap: 8px;
  justify-content: center;
  flex-wrap: wrap;
}
.quick-chip {
  padding: 4px 12px;
  border-radius: 100px;
  border: 1px solid var(--seam-1);
  background: var(--bg-panel);
  color: var(--text-4);
  font-size: 12px;
  font-family: var(--font-mono);
  font-weight: 500;
  cursor: pointer;
  transition: all var(--duration-fast);
}
.quick-chip:hover {
  border-color: var(--seam-2);
  color: var(--text-2);
  background: var(--bg-surface);
}
</style>
