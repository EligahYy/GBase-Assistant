<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useMessage } from 'naive-ui'
import { CopyOutline, CheckmarkOutline } from '@vicons/ionicons5'
import { NIcon } from 'naive-ui'
import hljs from 'highlight.js/lib/core'
import sql from 'highlight.js/lib/languages/sql'

hljs.registerLanguage('sql', sql)

const props = defineProps<{ sql: string; streaming?: boolean }>()
const naiveMsg = useMessage()
const copied = ref(false)
const highlighted = ref('')

onMounted(() => {
  refreshHighlight()
})

watch(() => props.sql, () => {
  refreshHighlight()
})

watch(() => props.streaming, () => {
  refreshHighlight()
})

function refreshHighlight() {
  try {
    const result = hljs.highlight(props.sql, { language: 'sql' })
    highlighted.value = result.value
  } catch {
    highlighted.value = escapeHtml(props.sql)
  }
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function copySQL() {
  navigator.clipboard.writeText(props.sql).then(() => {
    copied.value = true
    naiveMsg.success('已复制')
    setTimeout(() => { copied.value = false }, 2000)
  })
}
</script>

<template>
  <div class="sql-block">
    <div class="sql-header">
      <div class="sql-meta">
        <span class="sql-dot sql-dot-purple" />
        <span class="sql-dot sql-dot-blue" />
        <span class="sql-dot sql-dot-green" />
        <span class="sql-lang">sql</span>
      </div>
      <button class="copy-btn" :class="{ copied }" @click="copySQL">
        <n-icon :component="copied ? CheckmarkOutline : CopyOutline" size="14" />
        <span>{{ copied ? '已复制' : '复制' }}</span>
      </button>
    </div>
    <div class="sql-body">
      <pre class="sql-content"><code><span v-html="highlighted"></span><span v-if="streaming" class="sql-cursor">▍</span></code></pre>
    </div>
  </div>
</template>

<style scoped>
.sql-block {
  background: var(--code-bg);
  border-radius: var(--radius-md);
  overflow: hidden;
  margin: 12px 0 16px;
  border: 1px solid var(--code-border);
  box-shadow: var(--shadow-sm);
}

.sql-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 14px;
  background: var(--code-header-bg);
  border-bottom: 1px solid var(--code-border);
}

.sql-meta {
  display: flex;
  align-items: center;
  gap: 6px;
}
.sql-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}
.sql-dot-purple { background: #a259ff; }
.sql-dot-blue { background: #3b82f6; }
.sql-dot-green { background: #10b981; }

.sql-lang {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  margin-left: 4px;
}

.copy-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  background: transparent;
  border: 1px solid var(--code-border);
  border-radius: 6px;
  color: var(--text-muted);
  font-size: 12px;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: all 0.15s ease;
}
.copy-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--border-strong);
}
.copy-btn.copied {
  border-color: var(--success);
  color: var(--success);
  background: rgba(16, 185, 129, 0.08);
}

.sql-body {
  overflow-x: auto;
}
.sql-content {
  margin: 0;
  padding: 14px 18px;
  font-family: var(--font-mono);
  font-size: 13.5px;
  color: var(--code-text);
  line-height: 1.65;
  white-space: pre;
}
.sql-content code {
  font-family: inherit;
  font-size: inherit;
  background: transparent;
  padding: 0;
  border-radius: 0;
  color: inherit;
}

/* Highlight.js token colors mapped to CSS vars */
.sql-content :deep(.hljs-keyword) { color: var(--code-keyword); font-weight: 600; }
.sql-content :deep(.hljs-function) { color: var(--code-function); }
.sql-content :deep(.hljs-string) { color: var(--code-string); }
.sql-content :deep(.hljs-number) { color: var(--code-number); }
.sql-content :deep(.hljs-comment) { color: var(--code-comment); font-style: italic; }
.sql-content :deep(.hljs-literal) { color: var(--code-keyword); }
.sql-content :deep(.hljs-operator) { color: var(--code-text); }
.sql-content :deep(.hljs-punctuation) { color: var(--code-text); }
.sql-content :deep(.hljs-property) { color: var(--code-function); }

.sql-cursor {
  animation: blink 0.9s step-end infinite;
  color: var(--text-muted);
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}
</style>
