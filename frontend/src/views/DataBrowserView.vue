<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  NSelect,
  NButton,
  NInput,
  NSpin,
  NEmpty,
  NPopover,
  NCheckbox,
  useMessage,
} from 'naive-ui'
import {
  ArrowBackOutline,
  RefreshOutline,
  ChevronForwardOutline,
  ChevronBackOutline,
  DownloadOutline,
  FilterOutline,
  GridOutline,
  ServerOutline,
  EyeOutline,
  EyeOffOutline,
  SearchOutline,
  CloseOutline,
} from '@vicons/ionicons5'
import { NIcon } from 'naive-ui'
import { useConnectionStore } from '@/stores/connection'
import { getSchemaTables, executeQuery, type TableSchemaItem, type QueryResultResponse } from '@/api/connections'

const router = useRouter()
const connStore = useConnectionStore()
const naiveMsg = useMessage()

const selectedConnId = ref<string | null>(null)
const connOptions = computed(() =>
  connStore.connections
    .filter(c => c.driver_type !== 'manual' && c.connection_tested)
    .map(c => ({ label: `${c.name}`, value: c.id })),
)

const tables = ref<TableSchemaItem[]>([])
const selectedTable = ref<string | null>(null)
const tablesLoading = ref(false)

const dataResult = ref<QueryResultResponse | null>(null)
const dataLoading = ref(false)
const dataError = ref<string | null>(null)

const pageSize = ref(100)
const currentPage = ref(1)
const totalRows = ref(0)

const sortColumn = ref<string | null>(null)
const sortDesc = ref(false)

const showFilter = ref(false)
const filterColumn = ref<string>('')
const filterOp = ref<string>('=')
const filterValue = ref('')
const filterOptions = [
  { label: '等于', value: '=' },
  { label: '不等于', value: '!=' },
  { label: '大于', value: '>' },
  { label: '小于', value: '<' },
  { label: '包含', value: 'LIKE' },
  { label: '不包含', value: 'NOT LIKE' },
  { label: 'IN', value: 'IN' },
]

const visibleColumns = ref<Set<string>>(new Set())
const showColumnPanel = ref(false)

const displayedColumns = computed(() => {
  if (!dataResult.value) return []
  return dataResult.value.columns.filter(c => visibleColumns.value.has(c))
})

const totalPages = computed(() => {
  if (totalRows.value <= 0) return 1
  return Math.ceil(totalRows.value / pageSize.value)
})

const pageStart = computed(() => {
  if (!dataResult.value) return 0
  return (currentPage.value - 1) * pageSize.value + 1
})

const pageEnd = computed(() => {
  if (!dataResult.value) return 0
  return pageStart.value + dataResult.value.rows.length - 1
})

watch(selectedConnId, async (id) => {
  if (!id) { tables.value = []; selectedTable.value = null; return }
  tablesLoading.value = true
  try {
    tables.value = await getSchemaTables(id)
  } catch (e: any) {
    naiveMsg.error('加载表列表失败')
    tables.value = []
  } finally {
    tablesLoading.value = false
  }
})

watch([selectedTable, currentPage, sortColumn, sortDesc], () => {
  if (selectedTable.value) loadTableData()
}, { flush: 'post' })

watch([filterColumn, filterOp, filterValue], () => {
  currentPage.value = 1
  if (selectedTable.value) loadTableData()
}, { flush: 'post' })

async function loadTableData() {
  if (!selectedConnId.value || !selectedTable.value) return
  dataLoading.value = true
  dataError.value = null

  const table = selectedTable.value
  const offset = (currentPage.value - 1) * pageSize.value
  const limit = pageSize.value

  let sql = `SELECT * FROM \`${table}\``

  if (filterColumn.value && filterValue.value) {
    const col = filterColumn.value
    const op = filterOp.value
    let val = filterValue.value
    if (op === 'LIKE' || op === 'NOT LIKE') {
      val = `%${val}%`
    }
    const isNumeric = !isNaN(Number(val)) && val.trim() !== ''
    const quotedVal = isNumeric ? val : `'${val.replace(/'/g, "\\'")}'`
    if (op === 'IN') {
      const parts = val.split(',').map(s => s.trim()).filter(Boolean)
      const quotedParts = parts.map(p => {
        const n = !isNaN(Number(p)) && p.trim() !== ''
        return n ? p : `'${p.replace(/'/g, "\\'")}'`
      })
      sql += ` WHERE \`${col}\` IN (${quotedParts.join(', ')})`
    } else {
      sql += ` WHERE \`${col}\` ${op} ${quotedVal}`
    }
  }

  if (sortColumn.value) {
    sql += ` ORDER BY \`${sortColumn.value}\` ${sortDesc.value ? 'DESC' : 'ASC'}`
  }

  sql += ` LIMIT ${offset}, ${limit}`

  try {
    const result = await executeQuery(selectedConnId.value, sql, limit)
    dataResult.value = result
    if (result.rows.length === limit) {
      await fetchTotalCount(table)
    } else {
      totalRows.value = offset + result.rows.length
    }
    if (visibleColumns.value.size === 0 && result.columns.length > 0) {
      result.columns.forEach(c => visibleColumns.value.add(c))
    }
  } catch (e: any) {
    dataError.value = e?.response?.data?.detail || e?.message || '查询失败'
    dataResult.value = null
  } finally {
    dataLoading.value = false
  }
}

async function fetchTotalCount(table: string) {
  if (!selectedConnId.value) return
  try {
    let countSql = `SELECT COUNT(*) AS cnt FROM \`${table}\``
    if (filterColumn.value && filterValue.value) {
      const col = filterColumn.value
      const op = filterOp.value
      let val = filterValue.value
      if (op === 'LIKE' || op === 'NOT LIKE') val = `%${val}%`
      const isNumeric = !isNaN(Number(val)) && val.trim() !== ''
      const quotedVal = isNumeric ? val : `'${val.replace(/'/g, "\\'")}'`
      if (op === 'IN') {
        const parts = val.split(',').map(s => s.trim()).filter(Boolean)
        const quotedParts = parts.map(p => {
          const n = !isNaN(Number(p)) && p.trim() !== ''
          return n ? p : `'${p.replace(/'/g, "\\'")}'`
        })
        countSql += ` WHERE \`${col}\` IN (${quotedParts.join(', ')})`
      } else {
        countSql += ` WHERE \`${col}\` ${op} ${quotedVal}`
      }
    }
    const result = await executeQuery(selectedConnId.value, countSql, 1)
    totalRows.value = Number(result.rows[0]?.[0]) || 0
  } catch {
    totalRows.value = (currentPage.value - 1) * pageSize.value + (dataResult.value?.rows.length || 0) + 1
  }
}

function handleSort(column: string) {
  if (sortColumn.value === column) {
    if (!sortDesc.value) {
      sortDesc.value = true
    } else {
      sortColumn.value = null
      sortDesc.value = false
    }
  } else {
    sortColumn.value = column
    sortDesc.value = false
  }
}

function handleTableClick(tableName: string) {
  selectedTable.value = tableName
  currentPage.value = 1
  sortColumn.value = null
  sortDesc.value = false
  filterColumn.value = ''
  filterValue.value = ''
  visibleColumns.value = new Set()
  dataResult.value = null
  totalRows.value = 0
}

function toggleColumn(col: string) {
  const next = new Set(visibleColumns.value)
  if (next.has(col)) next.delete(col)
  else next.add(col)
  visibleColumns.value = next
}

function showAllColumns() {
  if (dataResult.value) {
    visibleColumns.value = new Set(dataResult.value.columns)
  }
}

function formatCell(val: unknown): string {
  if (val === null || val === undefined) return 'NULL'
  return String(val)
}

function exportCSV() {
  if (!dataResult.value) return
  const cols = displayedColumns.value
  const rows = dataResult.value.rows
  let csv = '\uFEFF'
  csv += cols.join(',') + '\n'
  for (const row of rows) {
    const line = cols.map((c, i) => {
      const idx = dataResult.value!.columns.indexOf(c)
      const val = row[idx]
      if (val === null || val === undefined) return ''
      const s = String(val)
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
  a.download = `${selectedTable.value || 'export'}_${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(url)
  naiveMsg.success('导出成功')
}

onMounted(() => { connStore.loadConnections() })
</script>

<template>
  <div class="page-shell browser-page">
    <!-- Header -->
    <header class="browser-header">
      <div class="header-left">
        <button class="back-btn" @click="router.push('/')">
          <n-icon :component="ArrowBackOutline" size="16" />
          <span>返回</span>
        </button>
        <div class="header-brand">
          <div class="brand-icon">
            <n-icon :component="GridOutline" size="18" />
          </div>
          <span>数据浏览</span>
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
      </div>
    </header>

    <!-- Main -->
    <div class="browser-main">
      <!-- Left: Table List -->
      <aside class="table-sidebar">
        <div class="sidebar-header">
          <n-icon :component="ServerOutline" size="14" />
          <span>数据表</span>
          <span v-if="tables.length" class="table-count">{{ tables.length }}</span>
        </div>
        <n-spin v-if="tablesLoading" size="small" style="padding: 20px" />
        <div v-else-if="tables.length === 0" class="sidebar-empty">
          <div class="empty-icon">
            <n-icon :component="ServerOutline" size="24" />
          </div>
          <div class="empty-desc">{{ selectedConnId ? '暂无表' : '请先选择连接' }}</div>
        </div>
        <div v-else class="table-list">
          <div
            v-for="(t, i) in tables"
            :key="t.table_name"
            :class="['table-item', { active: selectedTable === t.table_name }]"
            @click="handleTableClick(t.table_name)"
          >
            <span class="table-name">{{ t.table_name }}</span>
            <span class="table-cols">{{ t.columns.length }} 列</span>
          </div>
        </div>
      </aside>

      <!-- Right: Data Panel -->
      <div class="data-panel">
        <!-- Toolbar -->
        <div v-if="selectedTable" class="data-toolbar">
          <div class="toolbar-left">
            <span class="table-title">{{ selectedTable }}</span>
            <span v-if="dataResult" class="row-info">
              {{ pageStart }}–{{ pageEnd }} / {{ totalRows }} 行
              <span v-if="dataResult.truncated" class="truncated-badge">已截断</span>
            </span>
          </div>
          <div class="toolbar-right">
            <button
              :class="['tool-btn', { active: showFilter }]"
              title="筛选"
              @click="showFilter = !showFilter"
            >
              <n-icon :component="FilterOutline" size="14" />
            </button>
            <n-popover trigger="click" placement="bottom" style="max-height: 300px; overflow: auto">
              <template #trigger>
                <button class="tool-btn" title="显示列">
                  <n-icon :component="EyeOutline" size="14" />
                </button>
              </template>
              <div class="column-panel">
                <div class="column-panel-header">
                  <n-button text size="tiny" @click="showAllColumns">全选</n-button>
                </div>
                <div
                  v-for="col in dataResult?.columns || []"
                  :key="col"
                  class="column-panel-item"
                  @click="toggleColumn(col)"
                >
                  <n-icon
                    :component="visibleColumns.has(col) ? EyeOutline : EyeOffOutline"
                    size="14"
                    :style="{ color: visibleColumns.has(col) ? 'var(--text-0)' : 'var(--text-3)' }"
                  />
                  <span>{{ col }}</span>
                </div>
              </div>
            </n-popover>
            <button class="tool-btn" title="导出 CSV" @click="exportCSV">
              <n-icon :component="DownloadOutline" size="14" />
            </button>
            <button class="tool-btn" title="刷新" @click="loadTableData">
              <n-icon :component="RefreshOutline" size="14" />
            </button>
          </div>
        </div>

        <!-- Filter Bar -->
        <div v-if="showFilter && selectedTable" class="filter-bar">
          <n-select
            v-model:value="filterColumn"
            :options="(dataResult?.columns || []).map(c => ({ label: c, value: c }))"
            placeholder="选择列"
            size="small"
            style="width: 140px"
            clearable
          />
          <n-select
            v-model:value="filterOp"
            :options="filterOptions"
            size="small"
            style="width: 100px"
          />
          <n-input
            v-model:value="filterValue"
            placeholder="输入值，IN 用逗号分隔"
            size="small"
            style="width: 200px"
            clearable
          />
        </div>

        <!-- Data Grid -->
        <div v-if="selectedTable" class="grid-wrap">
          <n-spin v-if="dataLoading" size="medium" style="padding: 40px" />
          <div v-else-if="dataError" class="grid-error">
            <div class="error-title">查询失败</div>
            <pre>{{ dataError }}</pre>
          </div>
          <template v-else-if="!dataResult || dataResult.rows.length === 0">
            <div class="grid-empty">
              <n-empty description="暂无数据" />
            </div>
          </template>
          <div v-else class="data-table-wrap">
            <table class="data-table-fancy">
              <thead>
                <tr>
                  <th
                    v-for="col in displayedColumns"
                    :key="col"
                    :class="{ sorted: sortColumn === col }"
                    @click="handleSort(col)"
                  >
                    {{ col }}
                    <span v-if="sortColumn === col" class="sort-indicator">
                      {{ sortDesc ? '↓' : '↑' }}
                    </span>
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, ri) in dataResult.rows" :key="ri">
                  <td
                    v-for="col in displayedColumns"
                    :key="col"
                    :class="{ null: row[dataResult.columns.indexOf(col)] === null }"
                  >
                    {{ formatCell(row[dataResult.columns.indexOf(col)]) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- Pagination -->
        <div v-if="selectedTable && dataResult && dataResult.rows.length > 0" class="pagination-bar">
          <n-select
            v-model:value="pageSize"
            :options="[
              { label: '50 条/页', value: 50 },
              { label: '100 条/页', value: 100 },
              { label: '200 条/页', value: 200 },
              { label: '500 条/页', value: 500 },
            ]"
            size="small"
            style="width: 100px"
          />
          <div class="page-controls">
            <button
              class="page-btn"
              :disabled="currentPage <= 1"
              @click="currentPage--"
            >
              <n-icon :component="ChevronBackOutline" size="14" />
            </button>
            <span class="page-info">{{ currentPage }} / {{ totalPages }}</span>
            <button
              class="page-btn"
              :disabled="currentPage >= totalPages"
              @click="currentPage++"
            >
              <n-icon :component="ChevronForwardOutline" size="14" />
            </button>
          </div>
        </div>

        <!-- Empty state when no table selected -->
        <template v-if="!selectedTable">
          <div class="no-table-empty">
            <n-empty description="选择左侧表以浏览数据" />
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.browser-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ── Header ── */
.browser-header {
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
  gap: 12px;
}

/* ── Main Layout ── */
.browser-main {
  flex: 1;
  display: flex;
  min-height: 0;
  overflow: hidden;
}

/* ── Table Sidebar ── */
.table-sidebar {
  width: 240px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  flex-shrink: 0;
  background: var(--bg-panel);
  border-right: 1px solid var(--seam-1);
}

.sidebar-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 16px 10px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-3);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  flex-shrink: 0;
}

.table-count {
  margin-left: auto;
  font-size: 11px;
  font-weight: 500;
  color: var(--text-3);
  background: var(--bg-surface);
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
  padding: 40px 16px;
  text-align: center;
}
.empty-icon {
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-surface);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-md);
  color: var(--text-3);
  margin-bottom: 12px;
}
.empty-desc {
  font-size: 12px;
  color: var(--text-3);
}

.table-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 8px 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.table-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 13px;
  color: var(--text-2);
  transition: all var(--duration-fast);
  border: 1px solid transparent;
}
.table-item:hover {
  background: var(--bg-hover);
  color: var(--text-1);
}
.table-item.active {
  background: var(--bg-hover);
  color: var(--text-0);
  font-weight: 500;
}

.table-name {
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 150px;
}

.table-cols {
  font-size: 11px;
  color: var(--text-3);
  font-family: var(--font-mono);
  flex-shrink: 0;
}

.table-item.active .table-cols {
  color: var(--text-3);
}

/* ── Data Panel ── */
.data-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}

/* ── Toolbar ── */
.data-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 20px;
  border-bottom: 1px solid var(--seam-1);
  background: var(--bg-void);
  flex-shrink: 0;
  gap: 12px;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.table-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-0);
  white-space: nowrap;
}

.row-info {
  font-size: 12px;
  color: var(--text-3);
  font-family: var(--font-mono);
  white-space: nowrap;
}

.truncated-badge {
  margin-left: 6px;
  font-size: 10px;
  color: var(--warning);
  background: rgba(217, 119, 6, 0.08);
  padding: 1px 5px;
  border-radius: 4px;
  border: 1px solid rgba(217, 119, 6, 0.15);
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 4px;
}

.tool-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border-radius: var(--radius-sm);
  border: 1px solid var(--seam-1);
  background: var(--bg-panel);
  color: var(--text-2);
  cursor: pointer;
  transition: all var(--duration-fast);
}
.tool-btn:hover {
  background: var(--bg-hover);
  border-color: var(--seam-2);
  color: var(--text-0);
}
.tool-btn.active {
  background: var(--text-0);
  border-color: var(--text-0);
  color: var(--bg-void);
}

/* ── Filter Bar ── */
.filter-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  border-bottom: 1px solid var(--seam-1);
  background: var(--bg-surface);
  flex-shrink: 0;
}

/* ── Grid ── */
.grid-wrap {
  flex: 1;
  overflow: auto;
  min-height: 0;
}

.grid-error {
  padding: 20px;
  margin: 16px;
  background: rgba(220, 38, 38, 0.04);
  border: 1px solid rgba(220, 38, 38, 0.15);
  border-radius: var(--radius-md);
}
.grid-error .error-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--error);
  margin-bottom: 8px;
}
.grid-error pre {
  font-size: 12px;
  color: var(--error);
  font-family: var(--font-mono);
  white-space: pre-wrap;
  margin: 0;
}

.grid-empty {
  padding: 60px 20px;
  height: 100%;
}

.data-table-wrap {
  overflow: auto;
  max-height: 100%;
}

.data-table-fancy thead th {
  cursor: pointer;
  user-select: none;
}
.data-table-fancy thead th:hover {
  background: var(--bg-hover);
}
.data-table-fancy thead th.sorted {
  color: var(--text-0);
}
.sort-indicator {
  margin-left: 4px;
  font-size: 11px;
}
.data-table-fancy tbody td.null {
  color: var(--text-3);
  font-style: italic;
}
.data-table-fancy tbody td {
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ── Pagination ── */
.pagination-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 20px;
  border-top: 1px solid var(--seam-1);
  background: var(--bg-void);
  flex-shrink: 0;
}

.page-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.page-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  padding: 0;
  border-radius: var(--radius-sm);
  border: 1px solid var(--seam-1);
  background: var(--bg-panel);
  color: var(--text-2);
  cursor: pointer;
  transition: all var(--duration-fast);
}
.page-btn:hover:not(:disabled) {
  background: var(--bg-hover);
  border-color: var(--seam-2);
}
.page-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.page-info {
  font-size: 13px;
  color: var(--text-2);
  font-family: var(--font-mono);
  min-width: 60px;
  text-align: center;
}

/* ── No Table Empty ── */
.no-table-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
}

/* ── Column Panel ── */
.column-panel {
  padding: 4px;
  min-width: 160px;
}
.column-panel-header {
  display: flex;
  justify-content: flex-end;
  padding: 2px 4px 6px;
  border-bottom: 1px solid var(--seam-1);
  margin-bottom: 4px;
}
.column-panel-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 8px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 12px;
  color: var(--text-2);
  transition: background var(--duration-fast);
}
.column-panel-item:hover {
  background: var(--bg-hover);
}

@media (max-width: 768px) {
  .table-sidebar { width: 180px; }
  .filter-bar { flex-wrap: wrap; }
  .browser-header { padding: 10px 16px; }
}
</style>
