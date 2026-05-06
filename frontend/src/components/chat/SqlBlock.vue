<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useMessage } from 'naive-ui'
import { CopyOutline, CheckmarkOutline, ThumbsUpOutline, ThumbsDownOutline, CreateOutline } from '@vicons/ionicons5'
import { NIcon } from 'naive-ui'
import hljs from 'highlight.js/lib/core'
import sqlLang from 'highlight.js/lib/languages/sql'
import { submitFeedback } from '@/api/feedback'

hljs.registerLanguage('sql', sqlLang)

const props = defineProps<{ sql: string; streaming?: boolean; messageId?: string }>()
const naiveMsg = useMessage()
const copied = ref(false)
const highlighted = ref('')
const feedbackState = ref<'accepted' | 'rejected' | 'modified' | null>(null)
const showEdit = ref(false)
const editedSql = ref('')

onMounted(() => { refreshHighlight() })
watch(() => props.sql, () => { refreshHighlight() })
watch(() => props.streaming, () => { refreshHighlight() })

function refreshHighlight() {
  try {
    highlighted.value = hljs.highlight(props.sql, { language: 'sql' }).value
  } catch {
    highlighted.value = escapeHtml(props.sql)
  }
}
function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}
function copySQL() {
  navigator.clipboard.writeText(props.sql).then(() => {
    copied.value = true
    naiveMsg.success('已复制')
    setTimeout(() => { copied.value = false }, 2000)
  })
}
async function sendFeedback(action: 'accepted' | 'rejected' | 'modified') {
  if (!props.messageId) return
  try {
    await submitFeedback({ message_id: props.messageId, action, modified_sql: action === 'modified' ? editedSql.value : undefined })
    feedbackState.value = action
    showEdit.value = false
    naiveMsg.success('反馈已提交')
  } catch (e: any) {
    naiveMsg.error(e.message || '提交失败')
  }
}
function startEdit() { editedSql.value = props.sql; showEdit.value = true }
function submitEdit() { sendFeedback('modified') }
</script>

<template>
  <div class="sql-block" :class="{ streaming }">
    <div class="sql-header">
      <span class="sql-label">SQL</span>
      <button class="sql-copy" :class="{ copied }" @click="copySQL">
        <n-icon :component="copied ? CheckmarkOutline : CopyOutline" size="13" />
      </button>
    </div>
    <div class="sql-body">
      <pre class="sql-content"><code><span v-html="highlighted"></span><span v-if="streaming" class="sql-cursor">▍</span></code></pre>
    </div>
    <div v-if="messageId && !streaming" class="sql-feedback">
      <div v-if="showEdit" class="edit-area">
        <textarea v-model="editedSql" class="edit-textarea" rows="3" />
        <div class="edit-actions">
          <button class="fb-btn primary" @click="submitEdit">提交修改</button>
          <button class="fb-btn" @click="showEdit = false">取消</button>
        </div>
      </div>
      <div v-else class="feedback-actions">
        <span v-if="feedbackState" class="fb-status" :class="feedbackState">
          {{ feedbackState === 'accepted' ? '✓ 已采纳' : feedbackState === 'rejected' ? '✗ 已拒绝' : '✎ 已修改' }}
        </span>
        <template v-else>
          <button class="fb-btn" title="SQL正确" @click="sendFeedback('accepted')">
            <n-icon :component="ThumbsUpOutline" size="13" />
          </button>
          <button class="fb-btn" title="SQL错误" @click="sendFeedback('rejected')">
            <n-icon :component="ThumbsDownOutline" size="13" />
          </button>
          <button class="fb-btn" title="修改SQL" @click="startEdit">
            <n-icon :component="CreateOutline" size="13" />
          </button>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sql-block {
  margin: 20px 0;
  border-radius: var(--radius-md);
  background: var(--bg-deep);
  border: 1px solid var(--seam-1);
  overflow: hidden;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.02);
  transition: all var(--duration-normal) var(--ease-out-expo);
  animation: terminalEnter 0.4s var(--ease-out-expo) both;
  position: relative;
}
.sql-block:hover {
  border-color: var(--seam-2);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.02), 0 4px 20px rgba(0,0,0,0.3);
  transform: translateY(-2px);
}
/* Top signal line */
.sql-block::before {
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px;
  background: linear-gradient(90deg, transparent, var(--accent-dim), transparent);
}

.sql-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 16px;
  background: linear-gradient(90deg, var(--bg-panel), var(--bg-deep));
  border-bottom: 1px solid var(--seam-1);
}
.sql-label {
  display: flex; align-items: center; gap: 6px;
  font-size: 10px; font-weight: 700;
  color: var(--text-4); letter-spacing: 0.08em;
  text-transform: uppercase;
  font-family: var(--font-mono);
}
.sql-label svg { width: 14px; height: 14px; color: var(--accent); }
.sql-copy {
  display: flex; align-items: center; justify-content: center;
  width: 28px; height: 28px; padding: 0;
  background: transparent; border: none; border-radius: 6px;
  color: var(--text-4); cursor: pointer;
  transition: all var(--duration-fast);
}
.sql-copy:hover { background: var(--bg-surface); color: var(--text-1); }
.sql-copy.copied { color: var(--accent); }

.sql-body { overflow-x: auto; }
.sql-content {
  margin: 0; padding: 18px 24px;
  font-family: var(--font-mono); font-size: 13px;
  color: var(--text-1); line-height: 1.7;
  white-space: pre;
}
.sql-content code {
  font-family: inherit; font-size: inherit;
  background: transparent; padding: 0; border-radius: 0; color: inherit;
}

/* Highlight.js overrides for terminal theme */
.sql-content :deep(.hljs-keyword) { color: #5eead4; font-weight: 600; }
.sql-content :deep(.hljs-function) { color: #7dd3fc; }
.sql-content :deep(.hljs-string) { color: #86efac; }
.sql-content :deep(.hljs-number) { color: #fdba74; }
.sql-content :deep(.hljs-comment) { color: #475569; font-style: italic; }
.sql-content :deep(.hljs-literal) { color: #5eead4; }
.sql-content :deep(.hljs-operator) { color: var(--text-1); }
.sql-content :deep(.hljs-punctuation) { color: var(--text-1); }
.sql-content :deep(.hljs-property) { color: #7dd3fc; }

.sql-cursor {
  display: inline-block;
  width: 2px; height: 16px;
  background: var(--accent);
  animation: cursorBlink 1s step-end infinite;
  vertical-align: middle;
  margin-left: 2px;
  box-shadow: 0 0 8px var(--accent-glow);
}

/* Feedback */
.sql-feedback {
  padding: 8px 16px;
  border-top: 1px solid var(--seam-1);
  background: transparent;
}
.feedback-actions {
  display: flex; align-items: center; gap: 4px;
}
.fb-btn {
  display: flex; align-items: center; justify-content: center;
  width: 28px; height: 28px; padding: 0;
  background: transparent; border: none; border-radius: 6px;
  color: var(--text-4); cursor: pointer;
  transition: all var(--duration-fast);
}
.fb-btn:hover { background: var(--bg-surface); color: var(--text-1); }
.fb-btn.primary {
  width: auto; padding: 5px 12px;
  background: var(--accent-dim); color: var(--accent);
  font-size: 12px; font-weight: 500;
  border: 1px solid var(--seam-2);
  border-radius: var(--radius-sm);
}
.fb-btn.primary:hover {
  background: var(--accent-glow); color: var(--text-0); border-color: var(--accent);
}
.fb-status {
  font-size: 12px; padding: 3px 10px; border-radius: 12px; font-weight: 500;
}
.fb-status.accepted { color: var(--success); background: rgba(34,197,94,0.1); }
.fb-status.rejected { color: var(--error); background: rgba(239,68,68,0.1); }
.fb-status.modified { color: var(--accent); background: var(--accent-dim); }

.edit-area {
  display: flex; flex-direction: column; gap: 8px;
}
.edit-textarea {
  width: 100%; padding: 10px 12px;
  border: 1px solid var(--seam-1); border-radius: var(--radius-sm);
  background: var(--bg-panel); color: var(--text-0);
  font-family: var(--font-mono); font-size: 13px;
  resize: vertical; outline: none;
  transition: border-color var(--duration-fast);
}
.edit-textarea:focus { border-color: var(--accent); }
.edit-actions { display: flex; gap: 8px; }

/* Light theme — SQL highlighting with proper contrast */
html[data-theme="light"] .sql-content :deep(.hljs-keyword) { color: #0f766e; }
html[data-theme="light"] .sql-content :deep(.hljs-function) { color: #0369a1; }
html[data-theme="light"] .sql-content :deep(.hljs-string) { color: #15803d; }
html[data-theme="light"] .sql-content :deep(.hljs-number) { color: #c2410c; }
html[data-theme="light"] .sql-content :deep(.hljs-literal) { color: #0f766e; }
html[data-theme="light"] .sql-content :deep(.hljs-property) { color: #0369a1; }
html[data-theme="light"] .sql-content :deep(.hljs-comment) { color: #94a3b8; }
html[data-theme="light"] .sql-content :deep(.hljs-operator) { color: var(--text-2); }
html[data-theme="light"] .sql-content :deep(.hljs-punctuation) { color: var(--text-2); }
</style>
