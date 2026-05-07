<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NSelect, useMessage } from 'naive-ui'
import { ArrowBackOutline, PlayOutline, TerminalOutline } from '@vicons/ionicons5'
import { NIcon } from 'naive-ui'
import { useConnectionStore } from '@/stores/connection'
import { executeQuery, type QueryResultResponse } from '@/api/connections'

const router = useRouter()
const connStore = useConnectionStore()
const naiveMsg = useMessage()

const selectedConnId = ref<string | null>(null)
const sqlText = ref('')
const isExecuting = ref(false)
const result = ref<QueryResultResponse | null>(null)
const error = ref<string | null>(null)
const history = ref<{ sql: string; result: QueryResultResponse | null; error: string | null; time: string }[]>([])

const connOptions = computed(() =>
  connStore.connections
    .filter(c => c.driver_type !== 'manual')
    .map(c => ({ label: `${c.name} (${c.driver_type})`, value: c.id }))
)

const selectedConn = computed(() =>
  connStore.connections.find(c => c.id === selectedConnId.value)
)

onMounted(() => { connStore.loadConnections() })

async function handleExecute() {
  const sql = sqlText.value.trim()
  if (!sql) { naiveMsg.warning('请输入 SQL'); return }
  if (!selectedConnId.value) { naiveMsg.warning('请选择数据库连接'); return }

  isExecuting.value = true
  error.value = null
  result.value = null

  try {
    const resp = await executeQuery(selectedConnId.value, sql, 1000)
    result.value = resp
    history.value.unshift({ sql, result: resp, error: null, time: new Date().toLocaleTimeString() })
    naiveMsg.success(`执行成功，${resp.row_count} 行`)
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || '执行失败'
    error.value = msg
    history.value.unshift({ sql, result: null, error: msg, time: new Date().toLocaleTimeString() })
    naiveMsg.error(msg)
  } finally {
    isExecuting.value = false
  }
}

function loadFromHistory(item: { sql: string }) {
  sqlText.value = item.sql
}

function formatCell(val: unknown): string {
  if (val === null || val === undefined) return 'NULL'
  return String(val)
}
</script>

<template>
  <div class="sql-editor-page">
    <!-- Header -->
    <header class="editor-header">
      <div class="header-left">
        <button class="back-btn" @click="router.push('/')">
          <n-icon :component="ArrowBackOutline" size="16" />
          <span>返回</span>
        </button>
        <div class="header-brand">
          <n-icon :component="TerminalOutline" size="18" />
          <span>SQL Editor</span>
        </div>
      </div>
      <div class="header-right">
        <n-select
          v-model:value="selectedConnId"
          :options="connOptions"
          placeholder="选择数据库连接"
          size="small"
          style="width: 220px"
        />
        <n-button
          type="primary"
          size="small"
          :loading="isExecuting"
          :disabled="!selectedConnId || !sqlText.trim()"
          @click="handleExecute"
        >
          <template #icon><n-icon :component="PlayOutline" /></template>
          执行
        </n-button>
      </div>
    </header>

    <!-- Main -->
    <div class="editor-main">
      <!-- Left: SQL Input + Result -->
      <div class="editor-workspace">
        <div class="sql-input-wrap">
          <textarea
            v-model="sqlText"
            class="sql-textarea"
            placeholder="输入 SQL 语句，如 SELECT * FROM users LIMIT 10..."
            spellcheck="false"
            @keydown.ctrl.enter="handleExecute"
          />
          <div class="sql-hint">Ctrl + Enter 执行</div>
        </div>

        <!-- Result -->
        <div v-if="result" class="result-section">
          <div class="result-header">
            <span class="result-label">查询结果</span>
            <span class="result-meta">{{ result.row_count }} 行 | {{ result.execution_time_ms }}ms</span>
          </div>
          <div class="result-table-wrap">
            <table class="result-table">
              <thead>
                <tr><th v-for="col in result.columns" :key="col">{{ col }}</th></tr>
              </thead>
              <tbody>
                <tr v-for="(row, ri) in result.rows" :key="ri">
                  <td v-for="(cell, ci) in row" :key="ci">{{ formatCell(cell) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-if="result.truncated" class="result-truncated">结果已截断，最多展示 1000 行</div>
        </div>

        <!-- Error -->
        <div v-if="error" class="error-section">
          <div class="error-label">执行失败</div>
          <pre class="error-content">{{ error }}</pre>
        </div>
      </div>

      <!-- Right: History -->
      <aside class="editor-sidebar">
        <div class="sidebar-title">执行历史</div>
        <div v-if="history.length === 0" class="sidebar-empty">暂无执行记录</div>
        <div v-else class="history-list">
          <div
            v-for="(item, i) in history"
            :key="i"
            class="history-item"
            :class="{ error: item.error }"
            @click="loadFromHistory(item)"
          >
            <div class="history-sql">{{ item.sql.slice(0, 60) }}{{ item.sql.length > 60 ? '...' : '' }}</div>
            <div class="history-meta">
              <span v-if="item.error" class="history-error">失败</span>
              <span v-else class="history-success">{{ item.result?.row_count }} 行</span>
              <span class="history-time">{{ item.time }}</span>
            </div>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.sql-editor-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-body);
}

/* Header */
.editor-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  border-bottom: 1px solid var(--seam-1);
  background: var(--bg-deep);
  gap: 16px;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}
.back-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-secondary);
  background: none;
  border: none;
  cursor: pointer;
}
.back-btn:hover { color: var(--text-primary); }
.header-brand {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}
.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* Main */
.editor-main {
  flex: 1;
  display: flex;
  min-height: 0;
  overflow: hidden;
}

/* Workspace */
.editor-workspace {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow-y: auto;
}

.sql-input-wrap {
  position: relative;
  padding: 16px 20px;
}
.sql-textarea {
  width: 100%;
  min-height: 140px;
  max-height: 300px;
  padding: 14px 16px;
  border: 1px solid var(--seam-2);
  border-radius: var(--radius-md);
  background: var(--bg-panel);
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-size: 14px;
  line-height: 1.6;
  resize: vertical;
  outline: none;
}
.sql-textarea:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-dim);
}
.sql-hint {
  position: absolute;
  bottom: 24px;
  right: 32px;
  font-size: 11px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  pointer-events: none;
}

/* Result */
.result-section {
  margin: 0 20px 20px;
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-md);
  background: var(--bg-panel);
  overflow: hidden;
}
.result-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  background: var(--bg-surface);
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
  overflow: auto;
  max-height: 400px;
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
  background: var(--bg-surface);
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
  padding: 6px 14px;
  font-size: 11px;
  color: var(--warning);
  text-align: center;
  border-top: 1px solid var(--seam-1);
  background: var(--bg-surface);
}

/* Error */
.error-section {
  margin: 0 20px 20px;
  padding: 14px 16px;
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: var(--radius-md);
  background: rgba(239, 68, 68, 0.08);
}
.error-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--error);
  margin-bottom: 8px;
}
.error-content {
  font-size: 13px;
  color: var(--error);
  font-family: var(--font-mono);
  white-space: pre-wrap;
  margin: 0;
}

/* Sidebar */
.editor-sidebar {
  width: 280px;
  border-left: 1px solid var(--seam-1);
  background: var(--bg-deep);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.sidebar-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-4);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 16px 16px 8px;
}
.sidebar-empty {
  font-size: 12px;
  color: var(--text-muted);
  text-align: center;
  padding: 32px 16px;
}
.history-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 12px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.history-item {
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  cursor: pointer;
  transition: all var(--duration-fast);
}
.history-item:hover {
  border-color: var(--seam-2);
  background: var(--bg-surface);
}
.history-item.error {
  border-left: 3px solid var(--error);
}
.history-sql {
  font-size: 12px;
  font-family: var(--font-mono);
  color: var(--text-1);
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
  margin-bottom: 6px;
}
.history-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
}
.history-success {
  color: var(--success);
  font-family: var(--font-mono);
}
.history-error {
  color: var(--error);
  font-family: var(--font-mono);
}
.history-time {
  color: var(--text-muted);
  font-family: var(--font-mono);
  margin-left: auto;
}

@media (max-width: 768px) {
  .editor-sidebar { display: none; }
  .editor-header { flex-wrap: wrap; }
}
</style>
