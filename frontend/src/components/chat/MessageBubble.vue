<script setup lang="ts">
import { computed } from 'vue'
import SqlBlock from './SqlBlock.vue'
import { parseContent } from '@/composables/useContentParser'
import type { Message } from '@/stores/chat'
import { marked } from 'marked'

const props = defineProps<{ message: Message }>()

const isUser = computed(() => props.message.role === 'user')

const segments = computed(() => {
  if (isUser.value) return [{ type: 'text' as const, content: props.message.content, complete: true }]
  const raw = props.message.isStreaming
    ? (props.message.streamContent ?? props.message.content)
    : props.message.content
  return parseContent(raw)
})

const isTyping = computed(() =>
  props.message.isStreaming && !props.message.streamContent
)

function renderMarkdown(text: string, streaming = false): string {
  try {
    if (streaming) {
      return marked.parseInline(text) as string
    }
    return marked.parse(text) as string
  } catch {
    return text
  }
}
</script>

<template>
  <div :class="['msg-row', isUser ? 'is-user' : 'is-assistant']">
    <div class="msg-wrapper">
      <!-- Assistant avatar (left) -->
      <div v-if="!isUser" class="avatar assistant-avatar">
        <svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18">
          <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/>
        </svg>
      </div>

      <!-- Content -->
      <div :class="['msg-content', isUser ? 'user-content' : 'assistant-content']">
        <!-- Typing indicator -->
        <div v-if="isTyping" class="thinking">
          <div class="thinking-inner">
            <span class="dot" />
            <span class="dot" />
            <span class="dot" />
            <span class="thinking-text">思考中</span>
          </div>
        </div>

        <template v-else>
          <template v-for="(seg, i) in segments" :key="i">
            <div
              v-if="seg.type === 'text' && isUser"
              class="text-segment"
              style="white-space: pre-wrap"
            >{{ seg.content }}</div>
            <div
              v-else-if="seg.type === 'text'"
              class="text-segment"
              :style="message.isStreaming ? 'white-space: pre-wrap' : ''"
              v-html="renderMarkdown(seg.content, message.isStreaming)"
            />
            <SqlBlock
              v-else-if="seg.content"
              :sql="seg.content"
              :streaming="!seg.complete"
            />
          </template>

          <span
            v-if="message.isStreaming && (segments[segments.length - 1] as any).type !== 'text'"
            class="cursor"
          >▍</span>
        </template>
      </div>

      <!-- User avatar (right) -->
      <div v-if="isUser" class="avatar user-avatar">
        <svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18">
          <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/>
        </svg>
      </div>
    </div>
  </div>
</template>

<style scoped>
.msg-row {
  padding: 18px 0;
}
.msg-row.is-assistant {
  background: transparent;
}
.msg-row.is-user {
  background: transparent;
}

.msg-wrapper {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  max-width: 900px;
  margin: 0 auto;
  padding: 0 24px;
}
@media (max-width: 1024px) {
  .msg-wrapper { max-width: 100%; padding: 0 18px; }
}
@media (max-width: 768px) {
  .msg-wrapper { gap: 10px; padding: 0 14px; }
}

.avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 2px;
}
.assistant-avatar {
  background: var(--accent);
  color: var(--text-inverse);
}
.user-avatar {
  background: var(--border-strong);
  color: var(--text-primary);
}

.msg-content {
  flex: 1;
  min-width: 0;
  font-size: 15px;
  line-height: 1.75;
  color: var(--text-primary);
}

.user-content {
  text-align: right;
}
.user-content .text-segment {
  display: inline-block;
  text-align: left;
  background: var(--bubble-user-bg);
  color: var(--bubble-user-text);
  padding: 10px 16px;
  border-radius: 18px;
  border-bottom-right-radius: 6px;
  max-width: 100%;
  word-break: break-word;
}

.assistant-content .text-segment {
  display: block;
  padding: 4px 0;
  max-width: 100%;
  word-break: break-word;
}

.assistant-content :deep(strong),
.assistant-content :deep(b) {
  font-weight: 600;
  color: var(--text-primary);
}
.assistant-content :deep(code) {
  font-family: var(--font-mono);
  font-size: 13px;
  background: var(--bg-active);
  padding: 2px 6px;
  border-radius: 5px;
  color: var(--accent);
}
html[data-theme="dark"] .assistant-content :deep(code) {
  color: var(--text-primary);
  background: var(--bg-tertiary);
}
.assistant-content :deep(em) {
  font-style: italic;
}
.assistant-content :deep(del) {
  text-decoration: line-through;
  opacity: 0.7;
}

/* 块级 Markdown 样式重置 */
.assistant-content .text-segment :deep(p) {
  margin-bottom: 10px;
}
.assistant-content .text-segment :deep(p:last-child) {
  margin-bottom: 0;
}
.assistant-content .text-segment :deep(p:empty) {
  display: none;
}
.assistant-content .text-segment :deep(h1),
.assistant-content .text-segment :deep(h2),
.assistant-content .text-segment :deep(h3),
.assistant-content .text-segment :deep(h4) {
  font-weight: 600;
  color: var(--text-primary);
  margin: 14px 0 8px;
}
.assistant-content .text-segment :deep(h1) { font-size: 18px; }
.assistant-content .text-segment :deep(h2) { font-size: 17px; }
.assistant-content .text-segment :deep(h3) { font-size: 16px; }
.assistant-content .text-segment :deep(h4) { font-size: 15px; }
.assistant-content .text-segment :deep(ul),
.assistant-content .text-segment :deep(ol) {
  padding-left: 20px;
  margin-bottom: 10px;
}
.assistant-content .text-segment :deep(li) {
  margin-bottom: 4px;
}
.assistant-content .text-segment :deep(pre) {
  background: var(--code-bg);
  border: 1px solid var(--code-border);
  border-radius: var(--radius-sm);
  padding: 10px 14px;
  margin: 10px 0;
  overflow-x: auto;
}
.assistant-content .text-segment :deep(pre code) {
  background: transparent;
  padding: 0;
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--code-text);
}

.cursor {
  display: inline-block;
  animation: blink 1s step-end infinite;
  color: var(--text-muted);
  font-size: 15px;
  margin-left: 3px;
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

/* Apple-style thinking dots */
.thinking {
  display: inline-flex;
  align-items: center;
  padding: 10px 0;
}
.thinking-inner {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 18px;
  box-shadow: var(--shadow-sm);
}
.dot {
  width: 7px;
  height: 7px;
  background: linear-gradient(135deg, var(--accent) 0%, var(--accent-hover) 100%);
  border-radius: 50%;
  animation: dotPulse 1.6s infinite ease-in-out both;
}
.dot:nth-child(1) { animation-delay: -0.4s; }
.dot:nth-child(2) { animation-delay: -0.2s; }
.dot:nth-child(3) { animation-delay: 0s; }

.thinking-text {
  font-size: 13px;
  color: var(--text-muted);
  font-weight: 500;
  margin-left: 4px;
  animation: textFade 2s ease-in-out infinite;
}

@keyframes dotPulse {
  0%, 100% { transform: scale(0.55); opacity: 0.4; }
  50% { transform: scale(1); opacity: 1; box-shadow: 0 0 6px rgba(59, 130, 246, 0.45); }
}

@keyframes textFade {
  0%, 100% { opacity: 0.55; }
  50% { opacity: 1; }
}
</style>
