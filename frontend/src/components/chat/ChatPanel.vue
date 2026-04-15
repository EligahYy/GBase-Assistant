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

const activeConn = computed(() =>
  connStore.connections.find(c => c.id === connStore.activeConnectionId)
)

// Auto-scroll to bottom on new messages
watch(() => chatStore.messages.length, async () => {
  await nextTick()
  scrollToBottom()
})

// Auto-scroll on streaming content update
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
    messagesContainer.value.scrollTo({
      top: messagesContainer.value.scrollHeight,
      behavior: 'smooth'
    })
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

function handleStop() {
  stopStream()
}

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
        <button class="icon-btn" @click="toggleSidebar">
          <n-icon :component="MenuOutline" size="18" />
        </button>
        <div v-if="activeConn" class="conn-badge">
          <n-icon :component="ServerOutline" size="13" />
          <span>{{ activeConn.name }}</span>
        </div>
        <div v-else class="conn-badge muted">
          <n-icon :component="ServerOutline" size="13" />
          <span>未选择数据库</span>
        </div>
      </div>
      <div class="header-right">
        <button class="theme-btn" @click="toggleTheme">
          <n-icon :component="theme === 'light' ? SunnyOutline : MoonOutline" size="18" />
        </button>
        <span class="model-tag">DeepSeek</span>
      </div>
    </header>

    <!-- Messages -->
    <div ref="messagesContainer" class="messages">
      <!-- Empty state -->
      <div v-if="chatStore.messages.length === 0" class="empty-state">
        <div class="empty-brand">
          <div class="empty-icon">G</div>
          <h2 class="empty-title">GBase 8a 数据库助手</h2>
          <p class="empty-sub">输入自然语言，自动生成 GBase 8a SQL 或解答数据库问题</p>
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
        <MessageBubble v-for="msg in chatStore.messages" :key="msg.id" :message="msg" />
      </div>
    </div>

    <!-- Input -->
    <div class="input-area">
      <div class="input-box" :class="{ disabled: isStreaming }">
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
        <!-- Stop button during streaming -->
        <button
          v-if="isStreaming"
          class="send-btn stop-btn"
          @click="handleStop"
        >
          <n-icon :component="StopCircleOutline" size="16" />
        </button>
        <!-- Normal send button -->
        <button
          v-else
          class="send-btn"
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
  background: var(--bg-body);
}

/* Header */
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 18px;
  border-bottom: 1px solid var(--border);
  height: var(--header-height);
  flex-shrink: 0;
  background: var(--bg-primary);
}
.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.icon-btn {
  display: none;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  padding: 0;
  background: none;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}
.icon-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
@media (max-width: 768px) {
  .icon-btn { display: flex; }
}
.theme-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  padding: 0;
  background: none;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}
.theme-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
.conn-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  padding: 5px 10px;
  border-radius: 20px;
  border: 1px solid var(--border);
}
.conn-badge.muted { opacity: 0.7; }
.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.model-tag {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-muted);
  background: var(--bg-secondary);
  padding: 4px 10px;
  border-radius: 20px;
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
  max-width: 900px;
  width: 100%;
  margin: 0 auto;
  padding: 20px 24px 140px;
}
@media (max-width: 1024px) {
  .messages-list { max-width: 100%; padding: 18px 20px 140px; }
}
@media (max-width: 768px) {
  .messages-list { padding: 14px 16px 140px; }
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
}
.empty-brand {
  margin-bottom: 36px;
}
.empty-icon {
  width: 56px;
  height: 56px;
  background: var(--accent);
  color: var(--text-inverse);
  border-radius: 16px;
  font-size: 24px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 18px;
}
.empty-title {
  font-size: 24px;
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: -0.02em;
  margin-bottom: 6px;
}
.empty-sub {
  font-size: 15px;
  color: var(--text-muted);
  line-height: 1.6;
  max-width: 420px;
}
.hint-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  max-width: 600px;
  width: 100%;
}
@media (max-width: 640px) {
  .hint-grid { grid-template-columns: 1fr; }
}
.hint-card {
  padding: 14px 16px;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  font-size: 14px;
  color: var(--text-secondary);
  text-align: left;
  cursor: pointer;
  font-family: var(--font-sans);
  transition: all 0.15s ease;
  line-height: 1.5;
  box-shadow: var(--shadow-sm);
}
.hint-card:hover {
  background: var(--bg-hover);
  border-color: var(--border-strong);
  color: var(--text-primary);
  transform: translateY(-1px);
  box-shadow: var(--shadow-md);
}

/* Input */
.input-area {
  flex-shrink: 0;
  padding: 14px 24px 24px;
  background: transparent;
  border-top: none;
}
.input-box {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  max-width: 820px;
  width: 100%;
  margin: 0 auto;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 24px;
  padding: 12px 14px 12px 18px;
  box-shadow:
    0 4px 6px -1px rgba(0, 0, 0, 0.06),
    0 2px 4px -1px rgba(0, 0, 0, 0.04),
    0 0 0 1px rgba(0, 0, 0, 0.02);
  transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}
.input-box:focus-within {
  border-color: var(--border-strong);
  box-shadow:
    0 8px 16px -4px rgba(0, 0, 0, 0.08),
    0 4px 8px -2px rgba(0, 0, 0, 0.04),
    0 0 0 1px rgba(0, 0, 0, 0.02);
  transform: translateY(-1px);
}
.input-box.disabled {
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
:deep(.n-input__state-border) { display: none !important; }
:deep(.n-input-wrapper) { padding: 0 !important; background: transparent !important; }

.send-btn {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  border: none;
  background: var(--border);
  color: var(--text-muted);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
  transition: all 0.15s ease;
  margin-bottom: 2px;
}
.send-btn.active {
  background: var(--accent);
  color: var(--text-inverse);
}
.send-btn.active:hover {
  background: var(--accent-hover);
  transform: scale(1.05);
}
.send-btn:disabled {
  cursor: not-allowed;
}
.stop-btn {
  background: var(--error);
  color: #fff;
}
.stop-btn:hover {
  background: #dc2626;
  transform: scale(1.05);
}

.input-hint {
  text-align: center;
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 8px;
}
</style>
