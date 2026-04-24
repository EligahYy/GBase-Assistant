<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useMessage } from 'naive-ui'
import { CopyOutline, CheckmarkOutline, ThumbsUpOutline, ThumbsDownOutline, CreateOutline } from '@vicons/ionicons5'
import { NIcon } from 'naive-ui'
import hljs from 'highlight.js/lib/core'
import sql from 'highlight.js/lib/languages/sql'
import { submitFeedback } from '@/api/feedback'

hljs.registerLanguage('sql', sql)

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
  background: var(--code-bg);
  border-radius: var(--radius-lg);
  overflow: hidden;
  margin: 16px 0 20px;
  border: 1px solid var(--code-border);
  box-shadow: var(--shadow-sm);
  animation: fadeInScale var(--duration-normal) var(--ease-out-expo) both;
  transition: box-shadow var(--duration-fast) var(--ease-smooth);
}
.sql-block:hover {
  box-shadow: var(--shadow-md);
}

.sql-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 16px;
  border-bottom: 1px solid var(--code-border);
}
.sql-label {
  font-size: 11px; font-weight: 600;
  color: var(--text-muted); letter-spacing: 0.08em;
  text-transform: uppercase;
}
.sql-copy {
  display: flex; align-items: center; justify-content: center;
  width: 28px; height: 28px; padding: 0;
  background: transparent; border: none; border-radius: 7px;
  color: var(--text-muted); cursor: pointer;
  transition: all var(--duration-fast) var(--ease-smooth);
}
.sql-copy:hover { background: var(--bg-hover); color: var(--text-primary); }
.sql-copy.copied { color: var(--success); }

.sql-body { overflow-x: auto; }
.sql-content {
  margin: 0; padding: 16px 20px;
  font-family: var(--font-mono); font-size: 13.5px;
  color: var(--code-text); line-height: 1.65;
  white-space: pre;
}
.sql-content code {
  font-family: inherit; font-size: inherit;
  background: transparent; padding: 0; border-radius: 0; color: inherit;
}

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
  animation: cursorBlink 0.9s step-end infinite;
  color: var(--accent); text-shadow: 0 0 6px var(--accent-glow);
}

/* Feedback */
.sql-feedback {
  padding: 8px 16px;
  border-top: 1px solid var(--code-border);
  background: transparent;
}
.feedback-actions {
  display: flex; align-items: center; gap: 4px;
}
.fb-btn {
  display: flex; align-items: center; justify-content: center;
  width: 28px; height: 28px; padding: 0;
  background: transparent; border: none; border-radius: 7px;
  color: var(--text-muted); cursor: pointer;
  transition: all var(--duration-fast) var(--ease-smooth);
}
.fb-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
.fb-btn.primary {
  width: auto; padding: 5px 12px;
  background: var(--accent); color: #fff; font-size: 12px; font-weight: 500;
  border-radius: var(--radius-sm);
}
.fb-btn.primary:hover { background: var(--accent-hover); }
.fb-status {
  font-size: 12px; padding: 3px 10px; border-radius: 12px; font-weight: 500;
}
.fb-status.accepted { color: var(--success); background: rgba(52,199,89,0.1); }
.fb-status.rejected { color: var(--error); background: rgba(255,59,48,0.1); }
.fb-status.modified { color: var(--accent); background: var(--accent-soft); }

.edit-area {
  display: flex; flex-direction: column; gap: 8px;
}
.edit-textarea {
  width: 100%; padding: 10px 12px;
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg-surface-solid); color: var(--text-primary);
  font-family: var(--font-mono); font-size: 13px;
  resize: vertical; outline: none;
  transition: border-color var(--duration-fast) var(--ease-smooth);
}
.edit-textarea:focus { border-color: var(--accent); }
.edit-actions { display: flex; gap: 8px; }
</style>
