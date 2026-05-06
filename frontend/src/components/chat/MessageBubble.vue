<script setup lang="ts">
import { computed } from 'vue'
import SqlBlock from './SqlBlock.vue'
import { parseContent } from '@/composables/useContentParser'
import type { Message } from '@/stores/chat'

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

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

/**
 * 轻量行内 Markdown 渲染器。
 * 将文本按 \n\n 分割为 <p> 段落，段落内处理行内格式（加粗、斜体、代码、链接）。
 * 不使用 marked.parse，避免流式过程中对不完整 Markdown 解析不稳定导致的布局跳动。
 */
function renderInlineMarkdown(text: string): string {
  if (!text) return ''
  const paragraphs = text.split(/\n\n+/)
  return paragraphs
    .map((p) => {
      const trimmed = p.trim()
      if (!trimmed) return ''
      let inline = escapeHtml(trimmed)
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/`(.+?)`/g, '<code>$1</code>')
        .replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
      // 单换行在段落内转为空格（符合 Markdown 语义）
      inline = inline.replace(/\n/g, ' ')
      return `<p>${inline}</p>`
    })
    .filter(Boolean)
    .join('')
}
</script>

<template>
  <div :class="['msg-row', isUser ? 'is-user' : 'is-assistant']">
    <div class="msg-wrapper">
      <!-- Assistant avatar -->
      <div v-if="!isUser" class="avatar assistant-avatar">
        <svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16">
          <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/>
        </svg>
      </div>

      <!-- Content -->
      <div :class="['msg-content', isUser ? 'user-content' : 'assistant-content']">
        <!-- AI meta info -->
        <div v-if="!isUser && !isTyping" class="msg-meta">
          <span class="msg-author">GBase 助手</span>
          <span class="msg-badge">AI</span>
          <span class="msg-time">刚刚</span>
        </div>

        <div v-if="isTyping" class="thinking">
          <div class="thinking-inner">
            <span class="dot" /><span class="dot" /><span class="dot" />
            <span class="thinking-text">思考中</span>
          </div>
        </div>

        <template v-else>
          <template v-for="(seg, i) in segments" :key="i">
            <div v-if="seg.type === 'text' && isUser" class="text-segment" style="white-space: pre-wrap">{{ seg.content }}</div>
            <div v-else-if="seg.type === 'text'" class="text-segment" v-html="renderInlineMarkdown(seg.content)" />
            <SqlBlock v-else-if="seg.content" :sql="seg.content" :streaming="!seg.complete" :message-id="message.id" />
          </template>

          <span v-if="message.isStreaming && (segments[segments.length - 1] as any).type !== 'text'" class="stream-cursor"></span>
        </template>
      </div>

      <!-- User avatar -->
      <div v-if="isUser" class="avatar user-avatar">
        <svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16">
          <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/>
        </svg>
      </div>
    </div>
  </div>
</template>

<style scoped>
.msg-row {
  padding: 24px 0;
  animation: msgEnter 0.5s var(--ease-out-expo) both;
}
.msg-row + .msg-row {
  border-top: 1px solid var(--seam-1);
}

.msg-wrapper {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  max-width: var(--max-content-width);
  margin: 0 auto;
  padding: 0 28px;
}
@media (max-width: 1024px) {
  .msg-wrapper { max-width: 100%; padding: 0 24px; }
}
@media (max-width: 768px) {
  .msg-wrapper { gap: 12px; padding: 0 16px; }
}

.avatar {
  width: 28px; height: 28px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; margin-top: 2px;
  position: relative;
}
.assistant-avatar {
  background: var(--bg-panel);
  border: 1px solid var(--seam-2);
  color: var(--accent);
}
.assistant-avatar::after {
  content: ''; position: absolute; inset: -2px; border-radius: 50%;
  border: 1px solid var(--accent-dim);
  animation: avatarRing 3s ease-out infinite;
}
.user-avatar {
  background: var(--bg-surface);
  border: 1px solid var(--seam-1);
  color: var(--text-3);
}

.msg-content {
  flex: 1; min-width: 0;
}

/* Meta info for assistant */
.msg-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.msg-author {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-0);
}
.msg-badge {
  font-size: 9px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--accent-dim);
  color: var(--accent);
  border: 1px solid var(--seam-1);
  font-family: var(--font-mono);
}
.msg-time {
  font-size: 11px;
  color: var(--text-4);
  font-family: var(--font-mono);
}

.user-content {
  text-align: right;
}
.user-content .text-segment {
  display: inline-block;
  text-align: left;
  background: var(--bg-surface);
  padding: 12px 18px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--seam-1);
  font-weight: 500;
  color: var(--text-0);
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
  max-width: 100%;
  word-break: break-word;
}

.assistant-content .text-segment {
  display: block;
  padding: 2px 0;
  font-size: 15px;
  line-height: 1.75;
  color: var(--text-1);
  max-width: 100%;
  word-break: break-word;
}

.assistant-content :deep(strong),
.assistant-content :deep(b) {
  font-weight: 600;
  color: var(--text-0);
}
.assistant-content :deep(code) {
  font-family: var(--font-mono);
  font-size: 13px;
  background: var(--bg-surface);
  padding: 2px 7px;
  border-radius: 5px;
  color: var(--accent);
  border: 1px solid var(--seam-1);
}
.assistant-content :deep(em) { font-style: italic; }
.assistant-content :deep(del) { text-decoration: line-through; opacity: 0.6; }

/* Paragraph spacing */
.assistant-content .text-segment :deep(p) { margin-bottom: 14px; }
.assistant-content .text-segment :deep(p:last-child) { margin-bottom: 0; }
.assistant-content .text-segment :deep(p:empty) { display: none; }

.assistant-content .text-segment :deep(a) {
  color: var(--accent);
  text-decoration: none;
  border-bottom: 1px solid transparent;
  transition: border-color var(--duration-fast);
}
.assistant-content .text-segment :deep(a:hover) {
  border-bottom-color: var(--accent);
}

.stream-cursor {
  display: inline-block;
  width: 2px;
  height: 18px;
  background: var(--accent);
  vertical-align: middle;
  margin-left: 2px;
  animation: cursorBlink 1s step-end infinite;
  border-radius: 1px;
  box-shadow: 0 0 8px var(--accent-glow);
}

/* Thinking indicator */
.thinking {
  display: inline-flex;
  align-items: center;
  padding: 10px 0;
}
.thinking-inner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: 100px;
}
.dot {
  width: 7px; height: 7px;
  background: var(--accent);
  border-radius: 50%;
  animation: signalDot 1.4s infinite ease both;
  box-shadow: 0 0 4px var(--accent-glow);
}
.dot:nth-child(1) { animation-delay: -0.32s; }
.dot:nth-child(2) { animation-delay: -0.16s; }
.dot:nth-child(3) { animation-delay: 0s; }

.thinking-text {
  font-size: 12px;
  color: var(--text-3);
  font-weight: 500;
  font-family: var(--font-mono);
}
</style>
