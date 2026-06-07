<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  NSelect,
  useMessage,
  NModal,
  NInput,
  NForm,
  NFormItem,
} from 'naive-ui'
import {
  ArrowBackOutline,
  PlayOutline,
  TerminalOutline,
  SaveOutline,
  TrashOutline,
  CreateOutline,
  BookmarkOutline,
  DownloadOutline,
  CodeSlashOutline,
  TimeOutline,
  FlashOutline,
} from '@vicons/ionicons5'
import { NIcon } from 'naive-ui'
import { useConnectionStore } from '@/stores/connection'
import { executeQuery, type QueryResultResponse } from '@/api/connections'
import {
  useSavedQueries,
  extractParams,
  applyParams,
  type SavedQuery,
} from '@/composables/useSavedQueries'

const router = useRouter()
const connStore = useConnectionStore()
const naiveMsg = useMessage()
const { queries: savedQueries, add: addSavedQuery, remove: removeSavedQuery, rename: renameSavedQuery } = useSavedQueries()

const selectedConnId = ref<string | null>(null)
const sqlText = ref('')
const isExecuting = ref(false)
const result = ref<QueryResultResponse | null>(null)
const error = ref<string | null>(null)
const history = ref<{ sql: string; result: QueryResultResponse | null; error: string | null; time: string }[]>([])

const showSaveModal = ref(false)
const saveName = ref('')

const showParamModal = ref(false)
const paramValues = ref<Record<string, string>>({})
const pendingParams = ref<string[]>([])

const connOptions = computed(() =>
  connStore.connections
    .filter(c => c.driver_type !== 'manual')
    .map(c => ({ label: `${c.name}`, value: c.id })),
)

onMounted(() => { connStore.loadConnections() })

async function doExecute(rawSql: string) {
  const sql = rawSql.trim()
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

function handleExecute() {
  const params = extractParams(sqlText.value)
  if (params.length > 0) {
    pendingParams.value = params
    paramValues.value = {}
    params.forEach(p => { paramValues.value[p] = '' })
    showParamModal.value = true
    return
  }
  doExecute(sqlText.value)
}

function confirmParamExecute() {
  const missing = pendingParams.value.filter(p => !paramValues.value[p]?.trim())
  if (missing.length > 0) {
    naiveMsg.warning(`请填写参数: ${missing.join(', ')}`)
    return
  }
  const replaced = applyParams(sqlText.value, paramValues.value)
  showParamModal.value = false
  doExecute(replaced)
}

function handleSave() {
  if (!sqlText.value.trim()) {
    naiveMsg.warning('SQL 为空')
    return
  }
  saveName.value = ''
  showSaveModal.value = true
}

function confirmSave() {
  if (!saveName.value.trim()) {
    naiveMsg.warning('请输入查询名称')
    return
  }
  addSavedQuery(saveName.value, sqlText.value)
  naiveMsg.success('已保存')
  showSaveModal.value = false
}

function loadSnippet(q: SavedQuery) {
  sqlText.value = q.sql
  naiveMsg.info(`已加载: ${q.name}`)
}

function loadFromHistory(item: { sql: string }) {
  sqlText.value = item.sql
}

const editingSnippetId = ref<string | null>(null)
const editingSnippetName = ref('')

function startRenameSnippet(q: SavedQuery) {
  editingSnippetId.value = q.id
  editingSnippetName.value = q.name
}

function confirmRenameSnippet() {
  if (editingSnippetId.value) {
    renameSavedQuery(editingSnippetId.value, editingSnippetName.value)
    editingSnippetId.value = null
  }
}

function exportCSV() {
  if (!result.value) return
  const cols = result.value.columns
  const rows = result.value.rows
  let csv = '\uFEFF'
  csv += cols.join(',') + '\n'
  for (const row of rows) {
    const line = row.map((cell) => {
      if (cell === null || cell === undefined) return ''
      const s = String(cell)
      if (s.includes(',') || s.includes('"') || s.includes('\n')) {
        return '"' + s.replace(/"/g, '""') + '"'
      }
      return s
    }).join(',')
    csv += line + '\n'
  }
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `query_result_${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(url)
  naiveMsg.success('导出成功')
}

function formatCell(val: unknown): string {
  if (val === null || val === undefined) return 'NULL'
  return String(val)
}

</script>

<template>
  <div class="page-shell sql-editor-page">
    <!-- Header -->
    <header class="editor-header">
      <div class="header-left">
        <button class="back-btn" @click="router.push('/')">
          <n-icon :component="ArrowBackOutline" size="16" />
          <span>返回</span>
        </button>
        <div class="header-brand">
          <div class="brand-icon">
            <n-icon :component="TerminalOutline" size="18" />
          </div>
          <span>SQL 编辑器</span>
        </div>
      </div>
      <div class="header-right">
        <n-select
          v-model:value="selectedConnId"
          :options="connOptions"
          placeholder="选择连接"
          size="small"
          style="width: 200px"
        />
        <button class="header-btn" @click="handleSave">
          <n-icon :component="SaveOutline" size="14" />
          <span>保存</span>
        </button>
        <button
          class="header-btn primary"
          :class="{ loading: isExecuting }"
          :disabled="!selectedConnId || !sqlText.trim()"
          @click="handleExecute"
        >
          <n-icon :component="PlayOutline" size="14" />
          <span>{{ isExecuting ? '执行中...' : '执行' }}</span>
        </button>
      </div>
    </header>

    <!-- Main -->
    <div class="editor-main">
      <!-- Left: Workspace -->
      <div class="editor-workspace">
        <!-- SQL Input -->
        <div class="input-card">
          <div class="input-header">
            <span class="input-label">
              <n-icon :component="CodeSlashOutline" size="14" />
              查询语句
            </span>
            <span class="input-hint">Ctrl + Enter 执行</span>
          </div>
          <textarea
            v-model="sqlText"
            class="sql-textarea"
            placeholder="输入 SQL 语句...&#10;使用 {{变量名}} 实现参数化查询"
            spellcheck="false"
            @keydown.ctrl.enter="handleExecute"
          />
        </div>

        <!-- Result -->
        <div v-if="result" class="result-card">
          <div class="result-header">
            <div class="result-title">
              <n-icon :component="FlashOutline" size="14" />
              <span>查询结果</span>
            </div>
            <div class="result-meta">
              <button class="meta-btn" @click="exportCSV">
                <n-icon :component="DownloadOutline" size="13" />
                导出 CSV
              </button>
              <span class="meta-text">{{ result.row_count }} 行 · {{ result.execution_time_ms }}ms</span>
            </div>
          </div>
          <div class="result-table-wrap">
            <table class="data-table-fancy">
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
        <div v-if="error" class="error-card">
          <div class="error-title">执行失败</div>
          <pre class="error-content">{{ error }}</pre>
        </div>
      </div>

      <!-- Right: Sidebar -->
      <aside class="editor-sidebar">
        <!-- Saved Queries -->
        <div class="sidebar-card">
          <div class="sidebar-header">
            <n-icon :component="BookmarkOutline" size="14" />
            <span>收藏查询</span>
            <span v-if="savedQueries.length" class="sidebar-count">{{ savedQueries.length }}</span>
          </div>
          <div v-if="savedQueries.length === 0" class="sidebar-empty">
            <div class="empty-icon">
              <n-icon :component="BookmarkOutline" size="20" />
            </div>
            <div class="empty-title">暂无收藏</div>
            <div class="empty-desc">点击「保存」按钮收藏常用查询</div>
          </div>
          <div v-else class="snippet-list">
            <div
              v-for="q in savedQueries"
              :key="q.id"
              class="snippet-item"
            >
              <template v-if="editingSnippetId === q.id">
                <input
                  v-model="editingSnippetName"
                  class="snippet-rename-input"
                  @keydown.enter="confirmRenameSnippet"
                  @blur="confirmRenameSnippet"
                />
              </template>
              <template v-else>
                <div class="snippet-main" @click="loadSnippet(q)">
                  <div class="snippet-name">{{ q.name }}</div>
                  <div class="snippet-preview">{{ q.sql.slice(0, 40) }}{{ q.sql.length > 40 ? '...' : '' }}</div>
                </div>
                <div class="snippet-actions">
                  <button class="snippet-action-btn" title="重命名" @click.stop="startRenameSnippet(q)">
                    <n-icon :component="CreateOutline" size="12" />
                  </button>
                  <button class="snippet-action-btn" title="删除" @click.stop="removeSavedQuery(q.id)">
                    <n-icon :component="TrashOutline" size="12" />
                  </button>
                </div>
              </template>
            </div>
          </div>
        </div>

        <!-- History -->
        <div class="sidebar-card">
          <div class="sidebar-header">
            <n-icon :component="TimeOutline" size="14" />
            <span>执行历史</span>
          </div>
          <div v-if="history.length === 0" class="sidebar-empty">
            <div class="empty-icon">
              <n-icon :component="TimeOutline" size="20" />
            </div>
            <div class="empty-title">暂无记录</div>
          </div>
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
        </div>
      </aside>
    </div>

    <!-- Save Modal -->
    <n-modal
      v-model:show="showSaveModal"
      preset="dialog"
      title="保存查询"
      positive-text="保存"
      negative-text="取消"
      :show-icon="false"
      @positive-click="confirmSave"
    >
      <n-input
        v-model:value="saveName"
        placeholder="输入查询名称"
        style="margin-top: 8px"
        @keydown.enter="confirmSave"
      />
    </n-modal>

    <!-- Param Modal -->
    <n-modal
      v-model:show="showParamModal"
      preset="dialog"
      title="参数输入"
      positive-text="执行"
      negative-text="取消"
      :show-icon="false"
      @positive-click="confirmParamExecute"
    >
      <n-form style="margin-top: 8px">
        <n-form-item
          v-for="p in pendingParams"
          :key="p"
          :label="p"
        >
          <n-input v-model:value="paramValues[p]" :placeholder="`输入 ${p} 的值`" />
        </n-form-item>
      </n-form>
    </n-modal>
  </div>
</template>

<style scoped>
.sql-editor-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ── Header ── */
.editor-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 24px;
  border-bottom: 1px solid var(--seam-1);
  background: var(--bg-void);
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-3);
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-md);
  padding: 6px 12px;
  cursor: pointer;
  transition: all var(--duration-fast);
}
.back-btn:hover {
  color: var(--text-0);
  border-color: var(--seam-2);
  background: var(--bg-surface);
}

.header-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-0);
}
.brand-icon {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-md);
  color: var(--text-2);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.header-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border-radius: var(--radius-md);
  border: 1px solid var(--seam-1);
  background: var(--bg-panel);
  color: var(--text-1);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--duration-fast);
}
.header-btn:hover:not(:disabled) {
  background: var(--bg-hover);
  border-color: var(--seam-2);
}
.header-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.header-btn.primary {
  background: var(--text-0);
  border-color: var(--text-0);
  color: var(--bg-void);
}
.header-btn.primary:hover:not(:disabled) {
  background: var(--text-1);
  border-color: var(--text-1);
}
.header-btn.primary.loading {
  opacity: 0.7;
}

/* ── Main Layout ── */
.editor-main {
  flex: 1;
  display: flex;
  min-height: 0;
  overflow: hidden;
  padding: 16px;
  gap: 16px;
}

.editor-workspace {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow-y: auto;
  gap: 16px;
}

/* ── Input Card ── */
.input-card {
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-lg);
  overflow: hidden;
  flex-shrink: 0;
  transition: border-color var(--duration-fast);
}
.input-card:hover {
  border-color: var(--seam-2);
}
.input-card:focus-within {
  border-color: var(--text-0);
}

.input-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--seam-1);
  background: var(--bg-surface);
}
.input-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-0);
  letter-spacing: 0.02em;
}
.input-label .n-icon {
  color: var(--text-3);
}
.input-hint {
  font-size: 11px;
  color: var(--text-3);
  font-family: var(--font-mono);
}

.sql-textarea {
  width: 100%;
  min-height: 160px;
  max-height: 320px;
  padding: 16px;
  border: none;
  background: var(--bg-panel);
  color: var(--text-0);
  font-family: var(--font-mono);
  font-size: 14px;
  line-height: 1.7;
  resize: vertical;
  outline: none;
}
.sql-textarea::placeholder {
  color: var(--text-3);
}

/* ── Result Card ── */
.result-card {
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-lg);
  overflow: hidden;
  animation: fadeInUp 0.25s var(--ease-out-expo) both;
}
.result-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--seam-1);
  background: var(--bg-surface);
}
.result-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-0);
  letter-spacing: 0.02em;
}
.result-title .n-icon {
  color: var(--text-3);
}
.result-meta {
  display: flex;
  align-items: center;
  gap: 12px;
}
.meta-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-2);
  background: none;
  border: none;
  cursor: pointer;
  transition: color var(--duration-fast);
}
.meta-btn:hover {
  color: var(--text-0);
  text-decoration: underline;
}
.meta-text {
  font-size: 11px;
  color: var(--text-3);
  font-family: var(--font-mono);
}

.result-table-wrap {
  overflow: auto;
  max-height: 400px;
}
.result-truncated {
  padding: 8px 16px;
  font-size: 11px;
  color: var(--warning);
  text-align: center;
  border-top: 1px solid var(--seam-1);
  background: var(--bg-surface);
  font-family: var(--font-mono);
}

/* ── Error Card ── */
.error-card {
  background: rgba(220, 38, 38, 0.04);
  border: 1px solid rgba(220, 38, 38, 0.15);
  border-radius: var(--radius-lg);
  padding: 16px;
  animation: fadeInUp 0.25s var(--ease-out-expo) both;
}
.error-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--error);
  margin-bottom: 8px;
  font-family: var(--font-mono);
}
.error-content {
  font-size: 13px;
  color: var(--error);
  font-family: var(--font-mono);
  white-space: pre-wrap;
  margin: 0;
  line-height: 1.6;
}

/* ── Sidebar ── */
.editor-sidebar {
  width: 280px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow: hidden;
  flex-shrink: 0;
}

.sidebar-card {
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-lg);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  flex: 1;
  transition: border-color var(--duration-fast);
}
.sidebar-card:hover {
  border-color: var(--seam-2);
}

.sidebar-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 14px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-3);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  border-bottom: 1px solid var(--seam-1);
  background: var(--bg-surface);
  flex-shrink: 0;
}
.sidebar-count {
  margin-left: auto;
  font-size: 11px;
  font-weight: 500;
  color: var(--text-3);
  background: var(--bg-panel);
  padding: 1px 6px;
  border-radius: 10px;
  border: 1px solid var(--seam-1);
}

.sidebar-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 32px 16px;
  text-align: center;
}
.empty-icon {
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-surface);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-md);
  color: var(--text-3);
  margin-bottom: 12px;
}
.empty-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-1);
  margin-bottom: 4px;
}
.empty-desc {
  font-size: 12px;
  color: var(--text-3);
}

/* ── Snippets ── */
.snippet-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px;
}
.snippet-item {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  background: var(--bg-surface);
  border: 1px solid var(--seam-1);
  cursor: pointer;
  transition: all var(--duration-fast);
}
.snippet-item:hover {
  border-color: var(--seam-2);
  background: var(--bg-raised);
}
.snippet-main {
  flex: 1;
  min-width: 0;
}
.snippet-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.snippet-preview {
  font-size: 11px;
  color: var(--text-3);
  font-family: var(--font-mono);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-top: 2px;
}
.snippet-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  opacity: 0;
  transition: opacity var(--duration-fast);
}
.snippet-item:hover .snippet-actions {
  opacity: 1;
}
.snippet-action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  padding: 0;
  background: none;
  border: none;
  border-radius: 4px;
  color: var(--text-3);
  cursor: pointer;
  transition: all var(--duration-fast);
}
.snippet-action-btn:hover {
  color: var(--text-0);
  background: var(--bg-hover);
}
.snippet-rename-input {
  flex: 1;
  padding: 4px 8px;
  font-size: 12px;
  font-family: var(--font-sans);
  border: 1px solid var(--seam-2);
  border-radius: var(--radius-sm);
  outline: none;
  background: var(--bg-surface);
  color: var(--text-0);
}

/* ── History ── */
.history-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px;
}
.history-item {
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--bg-surface);
  border: 1px solid var(--seam-1);
  cursor: pointer;
  transition: all var(--duration-fast);
}
.history-item:hover {
  border-color: var(--seam-2);
  background: var(--bg-raised);
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
  color: var(--text-3);
  font-family: var(--font-mono);
  margin-left: auto;
}

@media (max-width: 768px) {
  .editor-sidebar { display: none; }
  .editor-header { flex-wrap: wrap; padding: 10px 16px; }
  .editor-main { padding: 12px; }
}
</style>
