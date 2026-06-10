<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
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
  SaveOutline,
  TrashOutline,
  CreateOutline,
  BookmarkOutline,
  DownloadOutline,
  CodeSlashOutline,
  FlashOutline,
} from '@vicons/ionicons5'
import { NIcon } from 'naive-ui'
import { useConnectionStore } from '@/stores/connection'
import { executeQuery, getSchemaTables, type QueryResultResponse, type TableSchemaItem } from '@/api/connections'
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

const schemaTables = ref<TableSchemaItem[]>([])
const expandedTables = ref<Set<string>>(new Set())
const schemaLoading = ref(false)

function toggleTable(tableName: string) {
  const next = new Set(expandedTables.value)
  if (next.has(tableName)) next.delete(tableName)
  else next.add(tableName)
  expandedTables.value = next
}

async function loadSchema() {
  if (!selectedConnId.value) { schemaTables.value = []; return }
  schemaLoading.value = true
  try {
    schemaTables.value = await getSchemaTables(selectedConnId.value)
    expandedTables.value = new Set()
  } catch {
    schemaTables.value = []
  } finally {
    schemaLoading.value = false
  }
}

onMounted(() => { connStore.loadConnections() })

watch(selectedConnId, () => { loadSchema() })

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

const showSchema = ref(true)
const lineNumbersRef = ref<HTMLElement | null>(null)
const lineCount = ref(1)

function updateLineCount() {
  lineCount.value = Math.max(1, sqlText.value.split('\n').length)
}

function syncScroll(e: Event) {
  const target = e.target as HTMLTextAreaElement
  if (lineNumbersRef.value) {
    lineNumbersRef.value.scrollTop = target.scrollTop
  }
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
        <span class="header-title">SQL 编辑器</span>
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
      <!-- Left: Editor + Result -->
      <div class="editor-workspace">
        <!-- SQL Input with line numbers -->
        <div class="input-card">
          <div class="input-header">
            <span class="input-label">
              <n-icon :component="CodeSlashOutline" size="14" />
              查询语句
            </span>
            <span class="input-hint">Ctrl + Enter 执行</span>
          </div>
          <div class="code-editor-wrap">
            <div class="line-numbers" ref="lineNumbersRef">
              <span v-for="n in lineCount" :key="n" class="line-num">{{ n }}</span>
            </div>
            <textarea
              v-model="sqlText"
              class="sql-textarea"
              placeholder="SELECT ..."
              spellcheck="false"
              @keydown.ctrl.enter="handleExecute"
              @scroll="syncScroll"
              @input="updateLineCount"
            />
          </div>
        </div>

        <!-- Progress bar -->
        <div v-if="isExecuting" class="exec-progress">
          <div class="exec-progress-bar"></div>
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

      <!-- Right: Schema Panel -->
      <aside class="editor-sidebar">
        <div class="sidebar-card schema-panel">
          <div class="sidebar-header">
            <span>表结构</span>
            <button class="sidebar-close-btn" @click="showSchema = !showSchema">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#999" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>
          <div class="sidebar-body">
            <div v-if="!selectedConnId" class="sidebar-empty">
              <p class="empty-desc">选择连接以查看表结构</p>
            </div>
            <div v-else-if="schemaLoading" class="sidebar-empty">
              <p class="empty-desc">加载中...</p>
            </div>
            <div v-else-if="schemaTables.length === 0" class="sidebar-empty">
              <p class="empty-desc">该连接暂无 Schema 信息</p>
            </div>
            <div v-else class="schema-list">
              <div
                v-for="table in schemaTables"
                :key="table.table_name"
                class="schema-table-group"
              >
                <div class="schema-table-name" @click="toggleTable(table.table_name)">
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" :stroke="expandedTables.has(table.table_name) ? '#999' : '#ccc'" stroke-width="2.5"
                    :style="{ transform: expandedTables.has(table.table_name) ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.15s' }">
                    <polyline points="9 18 15 12 9 6"/>
                  </svg>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#999" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/></svg>
                  <span>{{ table.table_name }}</span>
                </div>
                <div v-show="expandedTables.has(table.table_name)" class="schema-columns">
                  <div v-for="col in table.columns" :key="col" class="schema-col">
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#999" stroke-width="2"><line x1="8" y1="6" x2="16" y2="6"/></svg>
                    <span class="col-name">{{ col }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- History (collapsed below) -->
        <div class="sidebar-card history-panel">
          <div class="sidebar-header">
            <span>执行历史</span>
            <span v-if="history.length" class="sidebar-count">{{ history.length }}</span>
          </div>
          <div class="sidebar-body">
            <div v-if="history.length === 0" class="sidebar-empty">
              <p class="empty-desc">暂无记录</p>
            </div>
            <div v-else class="history-list">
              <div
                v-for="(item, i) in history.slice(0, 10)"
                :key="i"
                class="history-item"
                :class="{ error: item.error }"
                @click="loadFromHistory(item)"
              >
                <div class="history-sql">{{ item.sql.slice(0, 50) }}{{ item.sql.length > 50 ? '...' : '' }}</div>
                <div class="history-meta">
                  <span v-if="item.error" class="history-error">失败</span>
                  <span v-else class="history-success">{{ item.result?.row_count }} 行</span>
                  <span class="history-time">{{ item.time }}</span>
                </div>
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
  background: var(--bg-page);
}

/* ── Header ── */
.editor-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 24px;
  height: 48px;
  border-bottom: 1px solid var(--border-card);
  background: var(--bg-header);
  flex-shrink: 0;
}

.header-left { display: flex; align-items: center; gap: 12px; }
.header-right { display: flex; align-items: center; gap: 8px; }

.back-btn {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 13px; color: var(--text-3);
  background: var(--bg-panel); border: 1px solid var(--seam-1);
  border-radius: var(--radius-md); padding: 5px 10px;
  cursor: pointer; transition: all var(--duration-fast);
}
.back-btn:hover { color: var(--text-0); border-color: var(--seam-2); }
.header-title { font-size: 15px; font-weight: 600; color: var(--text-brand); }

.header-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 7px 14px; border-radius: var(--radius-md);
  border: 1px solid var(--seam-1); background: var(--bg-panel);
  color: var(--text-1); font-size: 13px; font-weight: 500;
  cursor: pointer; transition: all var(--duration-fast);
}
.header-btn:hover:not(:disabled) { background: var(--bg-hover); border-color: var(--seam-2); }
.header-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.header-btn.primary { background: #16a34a; border-color: #16a34a; color: #fff; }
.header-btn.primary:hover:not(:disabled) { background: #15803d; }
.header-btn.primary.loading { opacity: 0.7; }

/* ── Main Layout ── */
.editor-main {
  flex: 1; display: flex; min-height: 0; overflow: hidden;
  padding: 20px; gap: 16px; background: var(--bg-page);
}
.editor-workspace {
  flex: 1; display: flex; flex-direction: column; min-width: 0;
  overflow-y: auto; gap: 12px;
}

/* ── Input Card with line numbers ── */
.input-card {
  background: var(--bg-header); border: 1px solid #e0e0e0; border-radius: 14px;
  overflow: hidden; flex-shrink: 0;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.input-card:focus-within { border-color: #bbb; box-shadow: 0 4px 16px rgba(0,0,0,0.06); }
.input-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 18px; border-bottom: 1px solid var(--border-card); background: var(--bg-page);
}
.input-label { display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; color: var(--text-0); }
.input-hint { font-size: 11px; color: var(--text-3); font-family: var(--font-mono); }

.code-editor-wrap {
  display: flex; background: #1a1a1a;
  min-height: 240px; max-height: 420px;
}
.line-numbers {
  width: 48px; flex-shrink: 0; overflow: hidden;
  padding: 18px 0; text-align: right;
  font-family: 'JetBrains Mono', monospace; font-size: 13px;
  line-height: 1.9; color: #555; user-select: none;
  border-right: 1px solid #2a2a2a;
}
.line-num { display: block; padding-right: 14px; }
.sql-textarea {
  flex: 1; min-width: 0; padding: 18px 20px;
  border: none; background: transparent; color: #d4d4d4;
  font-family: 'JetBrains Mono', 'SF Mono', monospace;
  font-size: 13px; line-height: 1.9; resize: none;
  outline: none; overflow-y: auto;
}
.sql-textarea::placeholder { color: #555; }

/* ── Execution Progress ── */
.exec-progress { height: 3px; background: #eee; border-radius: 2px; overflow: hidden; }
.exec-progress-bar {
  height: 100%; width: 35%;
  background: linear-gradient(90deg, transparent, #16a34a, transparent);
  border-radius: 2px; animation: progressFlow 1.5s infinite linear;
}

/* ── Result Card ── */
.result-card {
  background: var(--bg-header); border: 1px solid #e0e0e0; border-radius: 14px;
  overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.04);
  animation: fadeInUp 0.25s var(--ease-out-expo) both;
}
.result-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 18px; border-bottom: 1px solid var(--border-card); background: var(--bg-page);
}
.result-title { display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; color: var(--text-0); }
.result-meta { display: flex; align-items: center; gap: 12px; }
.meta-btn { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; color: var(--text-2); background: none; border: none; cursor: pointer; }
.meta-btn:hover { color: var(--text-0); }
.meta-text { font-size: 11px; color: var(--text-3); font-family: var(--font-mono); }
.result-table-wrap { overflow: auto; max-height: 400px; }
.result-truncated {
  padding: 8px 16px; font-size: 11px; color: var(--warning);
  text-align: center; border-top: 1px solid var(--seam-1);
  background: var(--bg-surface); font-family: var(--font-mono);
}

/* ── Error Card ── */
.error-card {
  background: #fef2f2; border: 1px solid #fecaca;
  border-radius: 14px; padding: 16px 20px;
  animation: fadeInUp 0.25s var(--ease-out-expo) both;
}
.error-title { font-size: 12px; font-weight: 600; color: var(--error); margin-bottom: 8px; }
.error-content { font-size: 13px; color: var(--error); font-family: var(--font-mono); white-space: pre-wrap; margin: 0; }

/* ── Sidebar ── */
.editor-sidebar { width: 220px; display: flex; flex-direction: column; gap: 12px; flex-shrink: 0; }
.sidebar-card {
  background: var(--bg-header); border: 1px solid #e0e0e0; border-radius: 14px;
  display: flex; flex-direction: column; overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.sidebar-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 14px; font-size: 11px; font-weight: 600;
  color: var(--text-0); border-bottom: 1px solid var(--border-card);
  background: var(--bg-page); flex-shrink: 0;
}
.sidebar-close-btn {
  display: flex; align-items: center; justify-content: center;
  width: 22px; height: 22px; padding: 0; background: none;
  border: none; border-radius: 4px; cursor: pointer;
}
.sidebar-close-btn:hover { background: var(--bg-hover); }
.sidebar-count {
  font-size: 10px; color: var(--text-3); background: var(--bg-panel);
  padding: 1px 6px; border-radius: 8px; border: 1px solid var(--seam-1);
}
.sidebar-body { flex: 1; overflow-y: auto; }
.sidebar-empty { padding: 24px 14px; text-align: center; }
.empty-desc { font-size: 12px; color: var(--text-3); }

/* Schema */
.schema-panel { flex: 1.4; }
.schema-list { padding: 6px; display: flex; flex-direction: column; gap: 2px; }
.schema-table-group { border-radius: 8px; overflow: hidden; }
.schema-table-name {
  display: flex; align-items: center; gap: 6px; padding: 6px 8px;
  font-size: 12px; color: var(--text-1); font-weight: 500;
  cursor: pointer; border-radius: 6px; font-family: var(--font-mono);
}
.schema-table-name:hover { background: var(--bg-hover); }
.schema-columns { padding-left: 18px; display: flex; flex-direction: column; gap: 1px; }
.schema-col {
  display: flex; align-items: center; gap: 6px;
  padding: 4px 8px; font-size: 11px; border-radius: 4px;
  color: var(--text-2); font-family: var(--font-mono);
}
.schema-col:hover { background: var(--bg-hover); }
.col-name { flex: 1; color: var(--text-1); }
.col-type { font-size: 10px; color: var(--text-3); background: var(--bg-deep); padding: 1px 5px; border-radius: 3px; }

/* History panel */
.history-panel { flex: 0.8; }
.history-list { padding: 4px; display: flex; flex-direction: column; gap: 2px; }
.history-item {
  padding: 8px 10px; border-radius: 6px; cursor: pointer;
  font-size: 11px; border: 1px solid transparent;
  transition: all var(--duration-fast);
}
.history-item:hover { background: var(--bg-hover); border-color: var(--seam-1); }
.history-item.error { border-left: 2px solid var(--error); }
.history-sql {
  font-family: var(--font-mono); color: var(--text-1);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.history-meta { display: flex; align-items: center; gap: 6px; margin-top: 3px; font-size: 10px; }
.history-success { color: var(--success); }
.history-error { color: var(--error); }
.history-time { color: var(--text-3); margin-left: auto; }

@media (max-width: 768px) {
  .editor-sidebar { display: none; }
  .editor-header { flex-wrap: wrap; padding: 10px 16px; }
  .editor-main { padding: 12px; }
}
</style>
