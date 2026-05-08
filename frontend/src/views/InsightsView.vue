<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { NSelect, NSpin, NEmpty, NButton, useMessage } from 'naive-ui'
import {
  ArrowBackOutline,
  SpeedometerOutline,
  ServerOutline,
  TrendingUpOutline,
  WarningOutline,
  CheckmarkCircleOutline,
  RefreshOutline,
  PulseOutline,
  LayersOutline,
} from '@vicons/ionicons5'
import { NIcon } from 'naive-ui'
import { useConnectionStore } from '@/stores/connection'
import { getSchemaTables, type TableSchemaItem } from '@/api/connections'
import { apiClient } from '@/api/client'

const router = useRouter()
const connStore = useConnectionStore()
const naiveMsg = useMessage()

const selectedConnId = ref<string | null>(null)
const loading = ref(false)
const tables = ref<TableSchemaItem[]>([])

interface OverviewData {
  connection_id: string
  timestamp: number
  table_stats: {
    columns: string[]
    rows: unknown[][]
    row_count: number
    execution_time_ms: number
    error?: string
  } | { error: string }
  processes: {
    columns: string[]
    rows: unknown[][]
    row_count: number
    execution_time_ms: number
    error?: string
  } | { error: string }
  status: Record<string, string | number> | { error: string }
  version: string | null
}

const overview = ref<OverviewData | null>(null)
const skewData = ref<Record<string, any>>({})
const skewLoading = ref<Set<string>>(new Set())

const connOptions = computed(() =>
  connStore.connections
    .filter(c => c.driver_type !== 'manual' && c.connection_tested)
    .map(c => ({ label: `${c.name}`, value: c.id })),
)

const statusEntries = computed(() => {
  if (!overview.value || 'error' in overview.value.status) return []
  const s = overview.value.status
  const entries: { label: string; key: string; value: string | number }[] = []
  const labels: Record<string, string> = {
    Threads_connected: '活跃连接',
    Threads_running: '运行中线程',
    Queries: '总查询数',
    Slow_queries: '慢查询数',
    Uptime: '运行时间(秒)',
  }
  for (const [key, val] of Object.entries(s)) {
    entries.push({ label: labels[key] || key, key, value: val })
  }
  return entries
})

const tableSizeRows = computed(() => {
  if (!overview.value || 'error' in overview.value.table_stats) return []
  const ts = overview.value.table_stats
  if ('rows' in ts && Array.isArray(ts.rows)) {
    const nameIdx = ts.columns.indexOf('Name')
    const engineIdx = ts.columns.indexOf('Engine')
    const rowsIdx = ts.columns.indexOf('Rows')
    const dataLenIdx = ts.columns.indexOf('Data_length')
    const indexLenIdx = ts.columns.indexOf('Index_length')
    return ts.rows.map(r => ({
      name: nameIdx >= 0 ? String(r[nameIdx]) : '',
      engine: engineIdx >= 0 ? String(r[engineIdx]) : '',
      rows: rowsIdx >= 0 ? Number(r[rowsIdx]) || 0 : 0,
      dataSize: dataLenIdx >= 0 ? Number(r[dataLenIdx]) || 0 : 0,
      indexSize: indexLenIdx >= 0 ? Number(r[indexLenIdx]) || 0 : 0,
    }))
  }
  return []
})

const processRows = computed(() => {
  if (!overview.value || 'error' in overview.value.processes) return []
  const ps = overview.value.processes
  if ('rows' in ps && Array.isArray(ps.rows)) {
    const idIdx = ps.columns.indexOf('Id')
    const userIdx = ps.columns.indexOf('User')
    const hostIdx = ps.columns.indexOf('Host')
    const dbIdx = ps.columns.indexOf('db')
    const cmdIdx = ps.columns.indexOf('Command')
    const timeIdx = ps.columns.indexOf('Time')
    const stateIdx = ps.columns.indexOf('State')
    const infoIdx = ps.columns.indexOf('Info')
    return ps.rows.map(r => ({
      id: idIdx >= 0 ? String(r[idIdx]) : '',
      user: userIdx >= 0 ? String(r[userIdx]) : '',
      host: hostIdx >= 0 ? String(r[hostIdx]) : '',
      db: dbIdx >= 0 ? String(r[dbIdx]) : '',
      command: cmdIdx >= 0 ? String(r[cmdIdx]) : '',
      time: timeIdx >= 0 ? Number(r[timeIdx]) || 0 : 0,
      state: stateIdx >= 0 ? String(r[stateIdx]) : '',
      info: infoIdx >= 0 ? String(r[infoIdx] || '') : '',
    }))
  }
  return []
})

watch(selectedConnId, async (id) => {
  if (!id) { overview.value = null; tables.value = []; return }
  await loadOverview()
  tables.value = await getSchemaTables(id)
})

async function loadOverview() {
  if (!selectedConnId.value) return
  loading.value = true
  try {
    const { data } = await apiClient.get<OverviewData>(`/insights/connections/${selectedConnId.value}/overview`)
    overview.value = data
  } catch (e: any) {
    naiveMsg.error(e?.response?.data?.detail || '加载失败')
    overview.value = null
  } finally {
    loading.value = false
  }
}

async function loadSkew(tableName: string) {
  if (!selectedConnId.value) return
  skewLoading.value.add(tableName)
  try {
    const { data } = await apiClient.get(`/insights/connections/${selectedConnId.value}/skew/${tableName}`)
    skewData.value[tableName] = data
  } catch {
    naiveMsg.error(`获取 ${tableName} 分布数据失败`)
  } finally {
    skewLoading.value.delete(tableName)
  }
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}

onMounted(() => { connStore.loadConnections() })
</script>

<template>
  <div class="page-shell insights-page">
    <!-- Header -->
    <header class="insights-header">
      <div class="header-left">
        <button class="back-btn" @click="router.push('/')">
          <n-icon :component="ArrowBackOutline" size="16" />
          <span>返回</span>
        </button>
        <div class="header-brand">
          <div class="brand-icon">
            <n-icon :component="SpeedometerOutline" size="18" />
          </div>
          <span>性能洞察</span>
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
        <button
          class="header-btn"
          :class="{ loading: loading }"
          :disabled="!selectedConnId"
          @click="loadOverview"
        >
          <n-icon :component="RefreshOutline" size="14" />
          <span>{{ loading ? '刷新中...' : '刷新' }}</span>
        </button>
      </div>
    </header>

    <!-- Main -->
    <div class="insights-main">
      <div v-if="!selectedConnId" class="page-empty">
        <n-empty description="选择数据库连接以查看性能数据" />
      </div>
      <n-spin v-else-if="loading" size="large" style="margin-top: 80px" />
      <template v-else-if="overview">
        <!-- Status Cards -->
        <div class="status-section">
          <div class="section-label">
            <n-icon :component="PulseOutline" size="14" />
            <span>运行状态</span>
          </div>
          <div class="status-grid">
            <div
              v-for="entry in statusEntries"
              :key="entry.key"
              class="status-card"
            >
              <div class="status-label">{{ entry.label }}</div>
              <div class="status-value">
                {{ typeof entry.value === 'number' ? formatNumber(entry.value) : entry.value }}
              </div>
            </div>
            <div v-if="overview.version" class="status-card">
              <div class="status-label">数据库版本</div>
              <div class="status-value version">{{ overview.version }}</div>
            </div>
          </div>
        </div>

        <!-- Table Stats -->
        <div class="data-section">
          <div class="section-label">
            <n-icon :component="LayersOutline" size="14" />
            <span>表大小统计</span>
          </div>
          <div v-if="tableSizeRows.length === 0" class="section-empty">
            暂无表数据
          </div>
          <div v-else class="table-wrap">
            <table class="data-table-fancy">
              <thead>
                <tr>
                  <th>表名</th>
                  <th>引擎</th>
                  <th style="text-align: right">行数</th>
                  <th style="text-align: right">数据大小</th>
                  <th style="text-align: right">索引大小</th>
                  <th style="text-align: right">总计</th>
                  <th>分布</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="t in tableSizeRows" :key="t.name">
                  <td class="mono">{{ t.name }}</td>
                  <td>{{ t.engine }}</td>
                  <td style="text-align: right" class="mono">{{ formatNumber(t.rows) }}</td>
                  <td style="text-align: right" class="mono">{{ formatBytes(t.dataSize) }}</td>
                  <td style="text-align: right" class="mono">{{ formatBytes(t.indexSize) }}</td>
                  <td style="text-align: right" class="mono">{{ formatBytes(t.dataSize + t.indexSize) }}</td>
                  <td>
                    <button
                      v-if="!skewData[t.name]"
                      class="skew-btn"
                      :disabled="skewLoading.has(t.name)"
                      @click="loadSkew(t.name)"
                    >
                      {{ skewLoading.has(t.name) ? '检测中...' : '检测' }}
                    </button>
                    <template v-else-if="skewData[t.name].is_balanced !== undefined">
                      <span
                        :class="['skew-badge', skewData[t.name].is_balanced ? 'balanced' : 'skewed']"
                      >
                        <n-icon
                          :component="skewData[t.name].is_balanced ? CheckmarkCircleOutline : WarningOutline"
                          size="12"
                        />
                        {{ skewData[t.name].is_balanced ? '均衡' : '倾斜' }}
                        <span class="skew-ratio">{{ skewData[t.name].skew_ratio }}x</span>
                      </span>
                    </template>
                    <span v-else class="skew-error">检测失败</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- Skew Detail Panel -->
        <div
          v-for="[tableName, skew] in Object.entries(skewData).filter(([, s]) => s?.nodes)"
          :key="tableName"
          class="data-section"
        >
          <div class="section-label">
            <n-icon :component="TrendingUpOutline" size="14" />
            <span>{{ tableName }} — 节点分布</span>
            <span class="skew-summary">
              共 {{ formatNumber(skew.total) }} 行，{{ skew.node_count }} 个节点
            </span>
          </div>
          <div class="skew-nodes">
            <div
              v-for="node in skew.nodes"
              :key="node.node"
              class="skew-node"
              :style="{ flex: node.count }"
            >
              <div class="skew-node-bar"
                :style="{
                  background: node.count === skew.nodes[0].count
                    ? 'var(--text-0)'
                    : node.count === skew.nodes[skew.nodes.length - 1].count
                      ? 'var(--text-3)'
                      : 'var(--seam-2)'
                }"
              />
              <div class="skew-node-info">
                <div class="skew-node-label">{{ node.node }}</div>
                <div class="skew-node-count">{{ formatNumber(node.count) }}</div>
              </div>
            </div>
          </div>
        </div>

        <!-- Process List -->
        <div class="data-section">
          <div class="section-label">
            <n-icon :component="PulseOutline" size="14" />
            <span>当前进程</span>
          </div>
          <div v-if="processRows.length === 0" class="section-empty">
            暂无活跃进程
          </div>
          <div v-else class="table-wrap">
            <table class="data-table-fancy">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>用户</th>
                  <th>数据库</th>
                  <th>命令</th>
                  <th>时间(秒)</th>
                  <th>状态</th>
                  <th>SQL</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="p in processRows" :key="p.id">
                  <td class="mono">{{ p.id }}</td>
                  <td>{{ p.user }}</td>
                  <td>{{ p.db }}</td>
                  <td>
                    <span class="cmd-badge" :class="{ active: p.command === 'Query' }">
                      {{ p.command }}
                    </span>
                  </td>
                  <td class="mono">{{ p.time }}</td>
                  <td>{{ p.state }}</td>
                  <td class="mono sql-preview" :title="p.info">{{ p.info }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.insights-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ── Header ── */
.insights-header {
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
.header-btn.loading {
  opacity: 0.7;
}

/* ── Main ── */
.insights-main {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.page-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* ── Section ── */
.section-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-0);
  letter-spacing: 0.02em;
  margin-bottom: 12px;
}
.section-label .n-icon {
  color: var(--text-3);
}

.data-section {
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-lg);
  overflow: hidden;
  transition: border-color var(--duration-fast);
}
.data-section:hover {
  border-color: var(--seam-2);
}
.data-section .section-label {
  padding: 14px 16px 0;
  margin-bottom: 8px;
}

.section-empty {
  padding: 32px;
  text-align: center;
  font-size: 13px;
  color: var(--text-3);
}

/* ── Status Grid ── */
.status-section {
  animation: fadeInUp 0.25s var(--ease-out-expo) both;
}
.status-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 12px;
}
.status-card {
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-md);
  padding: 16px;
  transition: border-color var(--duration-fast);
}
.status-card:hover {
  border-color: var(--seam-2);
}
.status-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 8px;
}
.status-value {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-0);
  font-family: var(--font-mono);
  line-height: 1.2;
}
.status-value.version {
  font-size: 13px;
  color: var(--text-2);
  word-break: break-all;
}

/* ── Table Wrap ── */
.table-wrap {
  overflow: auto;
  max-height: 400px;
}

/* ── Skew ── */
.skew-btn {
  font-size: 11px;
  padding: 4px 10px;
  border-radius: var(--radius-sm);
  background: var(--bg-surface);
  border: 1px solid var(--seam-1);
  color: var(--text-2);
  cursor: pointer;
  transition: all var(--duration-fast);
  font-weight: 500;
}
.skew-btn:hover:not(:disabled) {
  border-color: var(--text-0);
  color: var(--text-0);
  background: var(--bg-hover);
}
.skew-btn:disabled {
  opacity: 0.5;
  cursor: wait;
}
.skew-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  padding: 3px 8px;
  border-radius: var(--radius-sm);
  border: 1px solid transparent;
  font-weight: 500;
}
.skew-badge.balanced {
  background: rgba(22, 163, 74, 0.08);
  color: var(--success);
  border-color: rgba(22, 163, 74, 0.15);
}
.skew-badge.skewed {
  background: rgba(217, 119, 6, 0.08);
  color: var(--warning);
  border-color: rgba(217, 119, 6, 0.15);
}
.skew-ratio {
  font-family: var(--font-mono);
  font-size: 10px;
  opacity: 0.8;
}
.skew-error {
  font-size: 11px;
  color: var(--error);
}

.skew-summary {
  margin-left: auto;
  font-size: 11px;
  color: var(--text-3);
  font-weight: 400;
}

.skew-nodes {
  display: flex;
  gap: 2px;
  padding: 0 16px 16px;
  min-height: 80px;
  align-items: stretch;
}
.skew-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 60px;
  gap: 6px;
}
.skew-node-bar {
  width: 100%;
  min-height: 4px;
  border-radius: 2px;
  transition: all var(--duration-fast);
}
.skew-node-info {
  text-align: center;
}
.skew-node-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-1);
  margin-bottom: 2px;
}
.skew-node-count {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-3);
}

/* ── Command Badge ── */
.cmd-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  font-size: 11px;
  background: var(--bg-surface);
  color: var(--text-3);
  border: 1px solid var(--seam-1);
}
.cmd-badge.active {
  background: var(--bg-hover);
  color: var(--text-0);
  border-color: var(--seam-2);
  font-weight: 500;
}

/* ── SQL Preview ── */
.sql-preview {
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
}

@media (max-width: 768px) {
  .status-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .insights-main {
    padding: 16px;
  }
  .insights-header {
    padding: 10px 16px;
  }
}
</style>
