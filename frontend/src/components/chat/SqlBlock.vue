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
    await submitFeedback({ message_id: props.messageId, action, original_sql: props.sql, modified_sql: action === 'modified' ? editedSql.value : undefined })
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
  margin: 16px 0;
  border-radius: var(--radius-md);
  background: var(--bg-deep);
  border: 1px solid var(--seam-1);
  overflow: hidden;
  transition: border-color var(--duration-fast);
  animation: fadeInUp 0.3s var(--ease-out-expo) both;
}
.sql-block:hover {
  border-color: var(--seam-2);
}

.sql-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px 14px;
  background: var(--bg-panel);
  border-bottom: 1px solid var(--seam-1);
}
.sql-label {
  display: flex; align-items: center; gap: 6px;
  font-size: 10px; font-weight: 600;
  color: var(--text-4); letter-spacing: 0.06em;
  text-transform: uppercase;
  font-family: var(--font-mono);
}
.sql-copy {
  display: flex; align-items: center; justify-content: center;
  width: 28px; height: 28px; padding: 0;
  background: transparent; border: none; border-radius: 6px;
  color: var(--text-4); cursor: pointer;
  transition: all var(--duration-fast);
}
.sql-copy:hover { background: var(--bg-hover); color: var(--text-1); }
.sql-copy.copied { color: var(--success); }

.sql-body { overflow-x: auto; }
.sql-content {
  margin: 0; padding: 14px 20px;
  font-family: var(--font-mono); font-size: 13px;
  color: var(--text-1); line-height: 1.7;
  white-space: pre;
}
.sql-content code {
  font-family: inherit; font-size: inherit;
  background: transparent; padding: 0; border-radius: 0; color: inherit;
}

/* Minimal SQL highlighting */
.sql-content :deep(.hljs-keyword) { color: var(--text-0); font-weight: 600; }
.sql-content :deep(.hljs-function) { color: var(--text-1); }
.sql-content :deep(.hljs-string) { color: var(--text-2); }
.sql-content :deep(.hljs-number) { color: var(--text-2); }
.sql-content :deep(.hljs-comment) { color: var(--text-4); font-style: italic; }
.sql-content :deep(.hljs-literal) { color: var(--text-0); font-weight: 500; }
.sql-content :deep(.hljs-operator) { color: var(--text-3); }
.sql-content :deep(.hljs-punctuation) { color: var(--text-3); }
.sql-content :deep(.hljs-property) { color: var(--text-1); }

.sql-cursor {
  display: inline-block;
  width: 2px; height: 16px;
  background: var(--text-0);
  animation: cursorBlink 1s step-end infinite;
  vertical-align: middle;
  margin-left: 2px;
}

/* Feedback */
.sql-feedback {
  padding: 6px 14px;
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
.fb-btn:hover { background: var(--bg-hover); color: var(--text-1); }
.fb-btn.primary {
  width: auto; padding: 5px 12px;
  background: var(--text-0); color: var(--bg-void);
  font-size: 12px; font-weight: 500;
  border: 1px solid var(--text-0);
  border-radius: var(--radius-sm);
}
.fb-btn.primary:hover {
  background: var(--text-1); border-color: var(--text-1);
}
.fb-status {
  font-size: 12px; padding: 3px 10px; border-radius: 12px; font-weight: 500;
}
.fb-status.accepted { color: var(--success); background: rgba(22,163,74,0.08); }
.fb-status.rejected { color: var(--error); background: rgba(220,38,38,0.08); }
.fb-status.modified { color: var(--text-0); background: var(--bg-hover); }

.edit-area {
  display: flex; flex-direction: column; gap: 8px;
}
.edit-textarea {
  width: 100%; padding: 10px 12px;
  border: 1px solid var(--seam-1); border-radius: var(--radius-sm);
  background: var(--bg-surface); color: var(--text-0);
  font-family: var(--font-mono); font-size: 13px;
  resize: vertical; outline: none;
  transition: border-color var(--duration-fast);
}
.edit-textarea:focus { border-color: var(--text-0); }
.edit-actions { display: flex; gap: 8px; }
</style>