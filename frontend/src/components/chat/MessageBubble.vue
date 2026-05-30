<script setup lang="ts">
import { computed, ref, watchEffect } from 'vue'
import SqlBlock from './SqlBlock.vue'
import ChartRenderer from './ChartRenderer.vue'
import { parseContent } from '@/composables/useContentParser'
import type { ChartConfig, Message } from '@/stores/chat'

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

const queryResult = computed(() => props.message.queryResult)
const hasQueryResult = computed(() => !!queryResult.value && queryResult.value.row_count > 0)

const viewMode = ref<'chart' | 'table' | 'raw'>('table')
const hasChart = computed(() => {
  if (props.message.chartConfig) return true
  if (!hasQueryResult.value) return false
  return queryResult.value!.columns.length >= 2
})

watchEffect(() => {
  if (props.message.chartConfig && hasQueryResult.value) {
    viewMode.value = 'chart'
  } else if (hasQueryResult.value) {
    viewMode.value = 'table'
  }
})

function formatCell(val: unknown): string {
  if (val === null || val === undefined) return 'NULL'
  if (typeof val === 'string') return val
  return String(val)
}

const sourceList = computed(() => {
  const raw = props.message.sources
  if (!raw) return []
  return raw
    .split('\n')
    .map((line) => line.replace(/^[\s\-•·]+/, '').trim())
    .filter(Boolean)
})

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function renderInlineMarkdown(text: string): string {
  if (!text) return ''

  const lines = text.split('\n')
  const blocks: string[] = []
  let listItems: string[] = []

  const flushList = () => {
    if (listItems.length) {
      const items = listItems.map((item) => `<li>${renderInline(item)}</li>`).join('')
      blocks.push(`<ul class="md-list">${items}</ul>`)
      listItems = []
    }
  }

  for (const rawLine of lines) {
    const line = rawLine.trimEnd()
    if (!line) {
      flushList()
      continue
    }

    const listMatch = line.match(/^(\s*)[-*+]\s+(.*)$/)
    if (listMatch && listMatch[2] !== undefined) {
      listItems.push(listMatch[2])
      continue
    }

    flushList()

    const headingMatch = line.match(/^(#{1,6})\s+(.*)$/)
    if (headingMatch && headingMatch[1] !== undefined && headingMatch[2] !== undefined) {
      const level = headingMatch[1].length
      const content = headingMatch[2]
      const sizes = ['18px', '16px', '15px', '14px', '13px', '12px']
      blocks.push(
        `<h${level} style="margin:12px 0 8px;font-size:${sizes[level - 1]};font-weight:600;color:var(--text-0);letter-spacing:-0.01em">${renderInline(content)}</h${level}>`
      )
      continue
    }

    const quoteMatch = line.match(/^>\s?(.*)$/)
    if (quoteMatch && quoteMatch[1] !== undefined) {
      blocks.push(
        `<blockquote style="margin:8px 0;padding:8px 12px;border-left:3px solid var(--text-3);background:var(--bg-panel);border-radius:0 6px 6px 0;color:var(--text-2);font-style:italic">${renderInline(quoteMatch[1])}</blockquote>`
      )
      continue
    }

    blocks.push(`<p style="margin:0 0 10px;line-height:1.75">${renderInline(line)}</p>`)
  }

  flushList()
  return blocks.join('')
}

function renderInline(text: string): string {
  let s = escapeHtml(text)
  s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  const boldOpen = (s.match(/\*\*/g) || []).length
  if (boldOpen % 2 === 1) {
    s = s.replace(/\*\*(?![^<]*>)/, '')
  }
  s = s.replace(/(^|[^*])\*(?!\*)(.+?)\*(?!\*)/g, '$1<em>$2</em>')
  s = s.replace(/`(.+?)`/g, '<code>$1</code>')
  s = s.replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
  return s
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

        <!-- Query Result with Chart + Table Toggle -->
        <div v-if="!isUser && !isTyping && hasQueryResult" class="result-block">
          <div class="result-header">
            <span class="result-label">查询结果</span>
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="result-meta">{{ queryResult!.row_count }} 行 | {{ queryResult!.execution_time_ms }}ms</span>
              <div v-if="hasChart" class="view-toggles">
                <button :class="['toggle-btn', { active: viewMode === 'chart' }]" @click="viewMode = 'chart'">图表</button>
                <button :class="['toggle-btn', { active: viewMode === 'table' }]" @click="viewMode = 'table'">表格</button>
                <button :class="['toggle-btn', { active: viewMode === 'raw' }]" @click="viewMode = 'raw'">原始</button>
              </div>
            </div>
          </div>
          <ChartRenderer
            v-if="viewMode === 'chart' && hasChart"
            :result="queryResult!"
            :chart-config="message.chartConfig ?? null"
          />
          <div v-if="viewMode === 'table'" class="result-table-wrap">
            <table class="result-table">
              <thead>
                <tr>
                  <th v-for="col in queryResult!.columns" :key="col">{{ col }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, ri) in queryResult!.rows" :key="ri">
                  <td v-for="(cell, ci) in row" :key="ci">{{ formatCell(cell) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <pre v-if="viewMode === 'raw'" class="raw-data">{{ JSON.stringify(queryResult, null, 2) }}</pre>
          <div v-if="queryResult!.truncated" class="result-truncated">结果已截断，最多展示 100 行</div>
        </div>

        <!-- RAG sources -->
        <details v-if="!isUser && !isTyping && sourceList.length" class="sources-block">
          <summary class="sources-summary">
            <span class="sources-label">引用来源</span>
            <span class="sources-count">{{ sourceList.length }}</span>
          </summary>
          <ul class="sources-list">
            <li v-for="(src, i) in sourceList" :key="`${src}-${i}`" class="sources-item">{{ src }}</li>
          </ul>
        </details>
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
  padding: 20px 0;
  animation: msgEnter 0.4s var(--ease-out-expo) both;
}
.msg-row + .msg-row {
  border-top: 1px solid var(--seam-1);
}

.msg-wrapper {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  max-width: var(--max-content-width);
  margin: 0 auto;
  padding: 0 28px;
}
@media (max-width: 1024px) {
  .msg-wrapper { max-width: 100%; padding: 0 24px; }
}
@media (max-width: 768px) {
  .msg-wrapper { gap: 10px; padding: 0 16px; }
}

.avatar {
  width: 28px; height: 28px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; margin-top: 2px;
}
.assistant-avatar {
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  color: var(--text-2);
}
.user-avatar {
  background: var(--bg-panel);
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
  margin-bottom: 6px;
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
  background: var(--bg-deep);
  color: var(--text-3);
  border: 1px solid var(--seam-1);
  font-family: var(--font-mono);
}

.user-content {
  text-align: right;
}
.user-content .text-segment {
  display: inline-block;
  text-align: left;
  background: var(--bg-panel);
  padding: 10px 16px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--seam-1);
  font-weight: 500;
  color: var(--text-0);
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
  background: var(--bg-panel);
  padding: 2px 7px;
  border-radius: 5px;
  color: var(--text-0);
  border: 1px solid var(--seam-1);
}
.assistant-content :deep(em) { font-style: italic; }
.assistant-content :deep(del) { text-decoration: line-through; opacity: 0.6; }

.assistant-content .text-segment :deep(p) { margin-bottom: 12px; }
.assistant-content .text-segment :deep(p:last-child) { margin-bottom: 0; }
.assistant-content .text-segment :deep(p:empty) { display: none; }

.assistant-content .text-segment :deep(a) {
  color: var(--text-0);
  text-decoration: none;
  border-bottom: 1px solid var(--seam-2);
  transition: border-color var(--duration-fast);
}
.assistant-content .text-segment :deep(a:hover) {
  border-bottom-color: var(--text-0);
}

.assistant-content :deep(.md-list) {
  margin: 6px 0 10px;
  padding-left: 20px;
  list-style: disc;
}
.assistant-content :deep(.md-list li) {
  margin-bottom: 4px;
  color: var(--text-1);
  line-height: 1.7;
}

.assistant-content :deep(blockquote) {
  margin: 8px 0;
}

.assistant-content :deep(h1),
.assistant-content :deep(h2),
.assistant-content :deep(h3),
.assistant-content :deep(h4),
.assistant-content :deep(h5),
.assistant-content :deep(h6) {
  margin: 10px 0 6px;
  font-weight: 600;
  color: var(--text-0);
}

.stream-cursor {
  display: inline-block;
  width: 2px;
  height: 18px;
  background: var(--text-0);
  vertical-align: middle;
  margin-left: 2px;
  animation: cursorBlink 1s step-end infinite;
  border-radius: 1px;
}

/* Thinking indicator */
.thinking {
  display: inline-flex;
  align-items: center;
  padding: 8px 0;
}
.thinking-inner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: 100px;
}
.dot {
  width: 6px; height: 6px;
  background: var(--text-3);
  border-radius: 50%;
  animation: signalDot 1.4s infinite ease both;
}
.dot:nth-child(1) { animation-delay: -0.32s; }
.dot:nth-child(2) { animation-delay: -0.16s; }
.dot:nth-child(3) { animation-delay: 0s; }

@keyframes signalDot {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

.thinking-text {
  font-size: 12px;
  color: var(--text-3);
  font-weight: 500;
  font-family: var(--font-mono);
}

/* Query Result Table */
.result-block {
  margin-top: 14px;
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-md);
  background: var(--bg-panel);
  overflow: hidden;
}
.result-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: var(--bg-deep);
  border-bottom: 1px solid var(--seam-1);
}
.result-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-0);
  font-family: var(--font-mono);
}
.result-meta {
  font-size: 11px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}
.result-table-wrap {
  overflow-x: auto;
  max-height: 320px;
  overflow-y: auto;
}
.result-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  font-family: var(--font-mono);
}
.result-table thead th {
  position: sticky;
  top: 0;
  background: var(--bg-deep);
  padding: 8px 12px;
  text-align: left;
  font-weight: 600;
  color: var(--text-0);
  border-bottom: 1px solid var(--seam-1);
  white-space: nowrap;
}
.result-table tbody td {
  padding: 6px 12px;
  color: var(--text-1);
  border-bottom: 1px solid var(--seam-1);
  white-space: nowrap;
}
.result-table tbody tr:hover {
  background: var(--bg-hover);
}
.result-truncated {
  padding: 6px 12px;
  font-size: 11px;
  color: var(--warning);
  text-align: center;
  border-top: 1px solid var(--seam-1);
  background: var(--bg-deep);
}

.view-toggles {
  display: flex;
  gap: 2px;
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: 6px;
  overflow: hidden;
}
.toggle-btn {
  padding: 3px 10px;
  font-size: 11px;
  border: none;
  background: transparent;
  color: var(--text-3);
  cursor: pointer;
  transition: all var(--duration-fast);
  font-family: var(--font-mono);
}
.toggle-btn.active {
  background: var(--bg-deep);
  color: var(--text-0);
  font-weight: 600;
}
.raw-data {
  padding: 12px;
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--text-2);
  max-height: 320px;
  overflow: auto;
  white-space: pre-wrap;
}

/* RAG sources */
.sources-block {
  margin-top: 12px;
  padding: 10px 14px;
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-md);
  max-width: 100%;
}
.sources-block[open] { padding-bottom: 12px; }
.sources-summary {
  display: flex; align-items: center; gap: 8px;
  cursor: pointer;
  list-style: none;
  user-select: none;
  font-size: 12px;
  color: var(--text-3);
  font-family: var(--font-mono);
}
.sources-summary::-webkit-details-marker { display: none; }
.sources-summary::before {
  content: '▸';
  display: inline-block;
  font-size: 10px;
  color: var(--text-4);
  transition: transform var(--duration-fast) var(--ease-smooth);
}
.sources-block[open] .sources-summary::before {
  transform: rotate(90deg);
}
.sources-label {
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--text-3);
}
.sources-count {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 100px;
  background: var(--bg-deep);
  color: var(--text-2);
  border: 1px solid var(--seam-1);
}
.sources-list {
  margin: 10px 0 0;
  padding: 0 0 0 20px;
  display: flex; flex-direction: column; gap: 4px;
}
.sources-item {
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.6;
  font-family: var(--font-mono);
  word-break: break-word;
}
</style>
