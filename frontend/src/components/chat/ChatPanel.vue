<script setup lang="ts">
import { ref, nextTick, watch, computed, inject } from 'vue'
import { useMessage } from 'naive-ui'
import { SendOutline, ServerOutline, MenuOutline, SunnyOutline, MoonOutline, StopCircleOutline } from '@vicons/ionicons5'
import { NIcon } from 'naive-ui'
import type { Ref } from 'vue'
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
          <n-icon :component="ServerOutline" size="12" />
          <span>{{ activeConn.name }}</span>
        </div>
        <div v-else class="conn-badge muted">
          <n-icon :component="ServerOutline" size="12" />
          <span>未选择数据库</span>
        </div>
      </div>
      <div class="header-right">
        <button class="header-icon-btn" @click="toggleTheme">
          <n-icon :component="theme === 'light' ? SunnyOutline : MoonOutline" size="18" />
        </button>
        <span class="model-label" :title="selectedModel">{{ modelDisplayName }}</span>
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
          <h2 class="empty-title">有什么可以帮您的？</h2>
          <p class="empty-sub">输入自然语言，自动生成 GBase 8a SQL 或解答数据库问题</p>
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
  background: var(--bg-body);
}

/* Header */
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 24px;
  height: var(--header-height);
  flex-shrink: 0;
  background: transparent;
  position: relative;
  z-index: 10;
}
.header-left, .header-right {
  display: flex;
  align-items: center;
  gap: 10px;
}
.header-icon-btn {
  display: none;
  align-items: center; justify-content: center;
  width: 34px; height: 34px; padding: 0;
  background: none; border: none; border-radius: var(--radius-sm);
  color: var(--text-secondary); cursor: pointer;
  transition: all var(--duration-fast) var(--ease-smooth);
}
.header-icon-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
@media (max-width: 768px) { .header-icon-btn { display: flex; } }

.conn-badge {
  display: flex; align-items: center; gap: 5px;
  font-size: 12px; font-weight: 500;
  color: var(--text-secondary);
  background: var(--bg-glass);
  backdrop-filter: blur(12px);
  padding: 5px 11px;
  border-radius: var(--radius-full);
  border: 1px solid var(--border);
}
.conn-badge.muted { opacity: 0.6; }
.model-label {
  font-size: 12px; font-weight: 500;
  color: var(--text-muted);
  background: var(--bg-glass);
  backdrop-filter: blur(12px);
  padding: 5px 11px;
  border-radius: var(--radius-full);
  border: 1px solid var(--border);
  letter-spacing: 0.02em;
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
  padding: 20px 24px 160px;
}
@media (max-width: 1024px) {
  .messages-list { max-width: 100%; padding: 18px 20px 160px; }
}
@media (max-width: 768px) {
  .messages-list { padding: 14px 16px 160px; }
  .chat-header { padding: 14px 16px; }
}

/* Empty state */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100%;
  padding: 40px 20px;
  text-align: center;
  animation: fadeInUp var(--duration-slow) var(--ease-out-expo) both;
}
.empty-brand {
  margin-bottom: 44px;
}
.monogram-wrap {
  position: relative;
  width: 72px; height: 72px;
  margin: 0 auto 24px;
}
.monogram {
  width: 72px; height: 72px;
  background: linear-gradient(135deg, var(--accent), var(--accent-hover));
  color: #fff;
  border-radius: 20px;
  font-size: 32px; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
  position: relative; z-index: 2;
  box-shadow: 0 4px 20px var(--accent-glow);
}
.monogram-glow {
  position: absolute;
  inset: -8px;
  background: radial-gradient(circle, var(--accent-glow) 0%, transparent 70%);
  border-radius: 28px;
  animation: breathe 3s ease-in-out infinite;
  z-index: 1;
}
.empty-title {
  font-size: var(--text-2xl);
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: -0.03em;
  margin-bottom: 8px;
}
.empty-sub {
  font-size: var(--text-base);
  color: var(--text-secondary);
  line-height: 1.6;
  max-width: 380px;
}

.hint-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  max-width: 560px;
  width: 100%;
}
@media (max-width: 640px) {
  .hint-grid { grid-template-columns: 1fr; }
}
.hint-card {
  padding: 16px 18px;
  background: var(--bg-glass);
  backdrop-filter: blur(16px);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  font-size: 14px;
  color: var(--text-secondary);
  text-align: left;
  cursor: pointer;
  font-family: var(--font-sans);
  transition: all var(--duration-fast) var(--ease-smooth);
  line-height: 1.5;
  box-shadow: var(--shadow-sm);
}
.hint-card:hover {
  background: var(--bg-surface);
  border-color: var(--border-strong);
  color: var(--text-primary);
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}

/* Input */
.input-area {
  flex-shrink: 0;
  padding: 16px 24px 28px;
  background: linear-gradient(to top, var(--bg-body) 60%, transparent);
  position: relative;
  z-index: 10;
}
.input-capsule {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  max-width: 760px;
  width: 100%;
  margin: 0 auto;
  background: var(--bg-glass);
  backdrop-filter: blur(20px) saturate(150%);
  -webkit-backdrop-filter: blur(20px) saturate(150%);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  padding: 12px 14px 12px 20px;
  box-shadow: var(--shadow-md), var(--shadow-glow);
  transition: all var(--duration-fast) var(--ease-smooth);
}
.input-capsule:focus-within {
  border-color: var(--accent);
  box-shadow: var(--shadow-lg), var(--shadow-glow);
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
  width: 36px; height: 36px;
  border-radius: 50%;
  border: none;
  background: var(--border);
  color: var(--text-muted);
  display: flex;
  align-items: center; justify-content: center;
  cursor: pointer; flex-shrink: 0;
  transition: all var(--duration-fast) var(--ease-spring);
  margin-bottom: 2px;
}
.send-circle.active {
  background: var(--accent);
  color: #fff;
  box-shadow: 0 2px 10px var(--accent-glow);
}
.send-circle.active:hover {
  background: var(--accent-hover);
  transform: scale(1.08);
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
  color: var(--text-muted);
  margin-top: 10px;
  letter-spacing: 0.02em;
}
</style>
