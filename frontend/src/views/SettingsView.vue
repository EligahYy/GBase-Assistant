<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { NInput, NButton, NSelect, NEmpty, NTag, useMessage, useDialog } from 'naive-ui'
import { useConnectionStore } from '@/stores/connection'
import { listConnections, createConnection, updateConnection, deleteConnection, getSchemaTables, testConnection, syncSchema, getConnectionsStatus, type ConnectionCreate, type TableSchemaItem } from '@/api/connections'
import { listModels, type ModelInfo } from '@/api/models'
import {
  ArrowBackOutline, ServerOutline, TrashOutline, CreateOutline, RefreshOutline,
  CheckmarkCircleOutline, CloseCircleOutline, WarningOutline,
  CubeOutline, PulseOutline, BarChartOutline, KeyOutline, LayersOutline, AddOutline, CloseOutline,
} from '@vicons/ionicons5'
import { NIcon } from 'naive-ui'
import { useRouter } from 'vue-router'
import { getHealthStatus, triggerReindex, getFeedbackStats, triggerEnrichFeedback, type HealthStatus, type FeedbackStats } from '@/api/admin'

const router = useRouter()
const connStore = useConnectionStore()
const naiveMsg = useMessage()
const dialog = useDialog()

// ── Model ──
const modelOptions = ref<{ label: string; value: string }[]>([])
const selectedModel = ref(localStorage.getItem('gbase_model') || 'deepseek/deepseek-chat')
watch(selectedModel, (val) => { localStorage.setItem('gbase_model', val) })

// ── Connection form ──
const driverOptions = [
  { label: '手动模式（粘贴 DDL）', value: 'manual' },
  { label: '原生 Python 驱动', value: 'native' },
]
const showAddForm = ref(false)
const editingId = ref<string | null>(null)
const newConn = ref<ConnectionCreate & { id?: string }>({
  name: '', host: '', port: 5258, database_name: '', username: '', password: '', driver_type: 'manual', description: '', schema_ddl: '',
})
const connections = ref(connStore.connections)

// ── System status ──
const health = ref<HealthStatus | null>(null)
const healthLoading = ref(false)
const adminToken = ref('')
const reindexLoading = ref(false)
const reindexResult = ref<string | null>(null)

// ── Feedback stats ──
const feedbackStats = ref<FeedbackStats | null>(null)
const feedbackLoading = ref(false)
const enrichLoading = ref(false)

// ── Connection actions ──
const testingConn = ref<Set<string>>(new Set())
const syncingConn = ref<Set<string>>(new Set())
const connLiveStatus = ref<Record<string, 'ok' | 'error' | 'unknown'>>({})

let statusPollTimer: ReturnType<typeof setInterval> | null = null

async function loadConnLiveStatus() {
  try {
    const resp = await getConnectionsStatus()
    for (const item of resp.connections) {
      connLiveStatus.value[item.id] = item.status === 'ok' ? 'ok' : item.status === 'testing' ? 'unknown' : 'error'
    }
  } catch { /* ignore */ }
}

onMounted(async () => {
  connections.value = await listConnections()
  try {
    const models = await listModels()
    modelOptions.value = models.map((m: ModelInfo) => ({ label: m.name, value: m.id }))
  } catch {
    modelOptions.value = [
      { label: 'DeepSeek Chat', value: 'deepseek/deepseek-chat' },
      { label: 'Qwen 2.5 72B Instruct', value: 'qwen/qwen2.5-72b-instruct' },
      { label: 'GPT-4o', value: 'openai/gpt-4o' },
    ]
  }
  await loadHealth()
  await loadConnLiveStatus()
  statusPollTimer = setInterval(loadConnLiveStatus, 5000)
})

onBeforeUnmount(() => {
  if (statusPollTimer) { clearInterval(statusPollTimer); statusPollTimer = null }
})

const expandedSchemas = ref<Set<string>>(new Set())
const schemaCache = ref<Map<string, TableSchemaItem[]>>(new Map())
const schemaLoading = ref<Set<string>>(new Set())

// ── Active tab ──
type TabKey = 'general' | 'connections' | 'admin'
const activeTab = ref<TabKey>('general')

async function loadHealth() {
  healthLoading.value = true
  try { health.value = await getHealthStatus() } catch { /* ignore */ } finally { healthLoading.value = false }
}

async function loadFeedbackStats() {
  if (!adminToken.value.trim()) return
  feedbackLoading.value = true
  try { feedbackStats.value = await getFeedbackStats(adminToken.value) } catch { feedbackStats.value = null } finally { feedbackLoading.value = false }
}

async function handleReindex() {
  if (!adminToken.value.trim()) { naiveMsg.warning('请输入管理 Token'); return }
  reindexLoading.value = true; reindexResult.value = null
  try {
    const resp = await triggerReindex(adminToken.value)
    const summary = Object.entries(resp.results).map(([k, v]) => `${k}: ${v} 条`).join('，')
    reindexResult.value = summary
    naiveMsg.success(`重建完成：${summary}`)
    await loadHealth()
  } catch (e: any) {
    const msg = e?.message || '重建失败'
    naiveMsg.error(msg)
    reindexResult.value = `失败：${msg}`
  } finally { reindexLoading.value = false }
}

async function handleEnrichFeedback() {
  if (!adminToken.value.trim()) { naiveMsg.warning('请输入管理 Token'); return }
  enrichLoading.value = true
  try {
    const resp = await triggerEnrichFeedback(adminToken.value)
    naiveMsg.success(`Enrich 完成：新增 ${resp.added} 条，跳过 ${resp.skipped} 条`)
    await loadFeedbackStats()
  } catch (e: any) { naiveMsg.error(e?.message || 'Enrich 失败') } finally { enrichLoading.value = false }
}

watch(adminToken, async (val) => {
  if (val.trim()) await loadFeedbackStats()
  else feedbackStats.value = null
})

const statusColor = (s: string, key?: string) => {
  if (key === 'default_model') return 'var(--text-2)'
  if (key === 'gbase_connections') {
    if (s === 'connected') return 'var(--success)'
    if (s === 'partial') return 'var(--warning)'
    if (s === 'disconnected' || s === 'no_connections') return 'var(--error)'
    return 'var(--text-3)'
  }
  if (s === 'connected' || s === 'ok') return 'var(--success)'
  if (s === 'degraded') return 'var(--warning)'
  return 'var(--error)'
}
const statusLabel = (s: string, key?: string) => {
  if (key === 'default_model') return s.length > 30 ? s.slice(0, 30) + '...' : s
  if (key === 'gbase_connections') {
    const map: Record<string, string> = { connected: '已连通', disconnected: '断开', partial: '部分连通', untested: '未测试', no_connections: '无连接', unknown: '未知' }
    return map[s] || s
  }
  if (s === 'connected' || s === 'ok') return '正常'
  if (s === 'degraded') return '降级'
  if (s === 'disconnected') return '断开'
  if (s === 'unreachable') return '不可达'
  return s
}

// ── Connection CRUD ──
async function handleTestConnection(connId: string) {
  testingConn.value.add(connId)
  try {
    const resp = await testConnection(connId)
    naiveMsg[resp.status === 'ok' ? 'success' : 'error'](resp.message)
    connections.value = await listConnections()
    await loadConnLiveStatus()
  } catch (e: any) { naiveMsg.error(e.message || '测试失败') } finally { testingConn.value.delete(connId) }
}

async function handleSyncSchema(connId: string) {
  syncingConn.value.add(connId)
  try {
    const resp = await syncSchema(connId)
    naiveMsg.success(`已同步 ${resp.tables} 个表`)
    connections.value = await listConnections()
    if (expandedSchemas.value.has(connId)) {
      schemaCache.value.delete(connId)
      const tables = await getSchemaTables(connId)
      schemaCache.value.set(connId, tables)
    }
  } catch (e: any) { naiveMsg.error(e.message || '同步失败') } finally { syncingConn.value.delete(connId) }
}

async function toggleSchemaView(connId: string) {
  if (expandedSchemas.value.has(connId)) { expandedSchemas.value.delete(connId); return }
  expandedSchemas.value.add(connId)
  if (!schemaCache.value.has(connId)) {
    schemaLoading.value.add(connId)
    try {
      const tables = await getSchemaTables(connId)
      schemaCache.value.set(connId, tables)
    } catch (e: any) {
      naiveMsg.error(e.message || '加载 Schema 失败')
      expandedSchemas.value.delete(connId)
    } finally { schemaLoading.value.delete(connId) }
  }
}

async function handleCreate() {
  if (!newConn.value.name.trim()) { naiveMsg.error('请输入连接名称'); return }
  try {
    await createConnection(newConn.value)
    naiveMsg.success('连接已创建')
    resetForm()
    connections.value = await listConnections()
    await connStore.loadConnections()
  } catch (e: any) { naiveMsg.error(e.message || '创建失败') }
}

async function handleUpdate() {
  if (!newConn.value.name.trim() || !editingId.value) { naiveMsg.error('请输入连接名称'); return }
  try {
    await updateConnection(editingId.value, newConn.value)
    naiveMsg.success('连接已更新')
    resetForm()
    connections.value = await listConnections()
    await connStore.loadConnections()
  } catch (e: any) { naiveMsg.error(e.message || '更新失败') }
}

function startEdit(conn: any) {
  editingId.value = conn.id
  newConn.value = {
    name: conn.name, host: conn.host || '', port: conn.port || 5258,
    database_name: conn.database_name || '', username: conn.username || '', password: '', driver_type: conn.driver_type || 'manual',
    description: conn.description || '', schema_ddl: conn.schema_ddl || '',
  }
  showAddForm.value = true
}

function resetForm() {
  editingId.value = null
  newConn.value = { name: '', host: '', port: 5258, database_name: '', username: '', password: '', driver_type: 'manual', description: '', schema_ddl: '' }
  showAddForm.value = false
}

function handleDelete(id: string, name: string) {
  dialog.warning({
    title: '删除连接', content: `确定删除数据库连接「${name}」？`,
    positiveText: '删除', negativeText: '取消',
    onPositiveClick: async () => {
      try { await deleteConnection(id); naiveMsg.success(`已删除 ${name}`); connections.value = await listConnections(); await connStore.loadConnections() }
      catch (e: any) { naiveMsg.error(e.message || '删除失败') }
    },
  })
}

const tabs: { key: TabKey; label: string; icon: any }[] = [
  { key: 'general', label: '通用', icon: CubeOutline },
  { key: 'connections', label: '连接', icon: ServerOutline },
  { key: 'admin', label: '管理', icon: KeyOutline },
]
</script>

<template>
  <div class="page-shell settings-page">
    <!-- Header -->
    <header class="settings-header">
      <div class="header-left">
        <button class="back-btn" @click="router.push('/')">
          <n-icon :component="ArrowBackOutline" size="16" />
          <span>返回</span>
        </button>
        <div class="header-brand">
          <div class="brand-icon">
            <n-icon :component="ServerOutline" size="18" />
          </div>
          <span>设置</span>
        </div>
      </div>
    </header>

    <!-- Body: Nav + Content -->
    <div class="settings-body">
      <aside class="settings-nav">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          :class="['nav-item', { active: activeTab === tab.key }]"
          @click="activeTab = tab.key"
        >
          <n-icon :component="tab.icon" size="18" />
          <span>{{ tab.label }}</span>
        </button>
      </aside>

      <main class="settings-main">
        <!-- ── General ── -->
        <section v-if="activeTab === 'general'" class="tab-panel">
          <div class="setting-card">
            <div class="card-label">
              <n-icon :component="LayersOutline" size="16" />
              <span>默认模型</span>
            </div>
            <div class="card-control">
              <n-select v-model:value="selectedModel" :options="modelOptions" />
            </div>
          </div>

          <div class="setting-card">
            <div class="card-label">
              <n-icon :component="PulseOutline" size="16" />
              <span>系统状态</span>
            </div>
            <div class="status-grid">
              <template v-if="health">
                <div
                  v-for="(value, key) in health.dependencies"
                  :key="key"
                  class="status-cell"
                >
                  <div class="status-dot" :style="{ background: statusColor(value, key) }" />
                  <span class="status-name">{{ { database: '数据库', llm_api: 'LLM API', vector_db: '向量数据库', default_model: '默认模型', gbase_connections: 'GBase 连接' }[key] || key }}</span>
                  <span class="status-value" :style="{ color: statusColor(value, key) }">{{ statusLabel(value, key) }}</span>
                </div>
              </template>
              <div v-else-if="healthLoading" class="status-empty">加载中...</div>
              <div v-else class="status-empty">状态获取失败</div>
            </div>
          </div>
        </section>

        <!-- ── Connections ── -->
        <section v-if="activeTab === 'connections'" class="tab-panel">
          <button
            v-if="!showAddForm"
            class="add-connection-btn"
            @click="showAddForm = true"
          >
            <n-icon :component="AddOutline" size="18" />
            <span>添加连接</span>
          </button>

          <div v-if="showAddForm" class="form-card">
            <div class="form-header">
              <span class="form-title">{{ editingId ? '编辑连接' : '新建连接' }}</span>
              <button class="form-close" @click="resetForm">
                <n-icon :component="CloseOutline" size="16" />
              </button>
            </div>
            <div class="form-body">
              <div class="form-field">
                <label>连接名称 *</label>
                <n-input v-model:value="newConn.name" placeholder="生产环境" />
              </div>
              <div class="form-row">
                <div class="form-field">
                  <label>主机地址</label>
                  <n-input v-model:value="newConn.host" placeholder="localhost" />
                </div>
                <div class="form-field">
                  <label>端口</label>
                  <n-input :value="String(newConn.port || '')" @update:value="v => newConn.port = v ? Number(v) : 5258" placeholder="5258" />
                </div>
              </div>
              <div class="form-row">
                <div class="form-field">
                  <label>数据库名</label>
                  <n-input v-model:value="newConn.database_name" placeholder="gbase_db" />
                </div>
                <div class="form-field">
                  <label>驱动类型</label>
                  <n-select v-model:value="newConn.driver_type" :options="driverOptions" />
                </div>
              </div>
              <div class="form-row">
                <div class="form-field">
                  <label>用户名</label>
                  <n-input v-model:value="newConn.username" placeholder="gbase_user" />
                </div>
                <div class="form-field">
                  <label>密码</label>
                  <n-input v-model:value="newConn.password" type="password" placeholder="••••••••" />
                </div>
              </div>
              <div class="form-field">
                <label>
                  Schema DDL
                  <span v-if="newConn.driver_type !== 'manual'" class="field-hint">驱动模式下可留空，通过「同步 Schema」自动获取</span>
                </label>
                <n-input v-model:value="newConn.schema_ddl" type="textarea" placeholder="粘贴 CREATE TABLE 语句..." :autosize="{ minRows: 4, maxRows: 10 }" />
              </div>
              <div class="form-actions">
                <n-button v-if="editingId" type="primary" @click="handleUpdate">更新连接</n-button>
                <n-button v-else type="primary" @click="handleCreate">保存连接</n-button>
              </div>
            </div>
          </div>

          <div v-if="connections.length === 0" class="empty-state">
            <n-empty description="暂无数据库连接" />
          </div>
          <div v-else class="connection-list">
            <div v-for="c in connections" :key="c.id" class="connection-card">
              <div class="conn-main">
                <div class="conn-icon-wrap">
                  <n-icon :component="ServerOutline" size="18" />
                </div>
                <div class="conn-info">
                  <span class="conn-name">{{ c.name }}</span>
                  <div class="conn-meta">
                    <span :class="['conn-badge', c.has_schema ? 'ok' : 'muted']">{{ c.has_schema ? '已配置 Schema' : '无 Schema' }}</span>
                    <span class="conn-badge">{{ c.driver_type === 'manual' ? '手动' : '原生驱动' }}</span>
                    <span v-if="c.driver_type !== 'manual'" :class="['conn-badge', connLiveStatus[c.id] === 'ok' ? 'ok' : connLiveStatus[c.id] === 'error' ? 'warn' : 'muted']">
                      {{ connLiveStatus[c.id] === 'ok' ? '已连通' : connLiveStatus[c.id] === 'error' ? '已断开' : '待检测' }}
                    </span>
                    <span class="conn-date">{{ new Date(c.created_at).toLocaleDateString() }}</span>
                  </div>
                </div>
              </div>
              <div class="conn-actions">
                <template v-if="c.driver_type !== 'manual'">
                  <button class="action-btn" :disabled="testingConn.has(c.id)" @click="handleTestConnection(c.id)">
                    {{ testingConn.has(c.id) ? '测试中...' : '测试' }}
                  </button>
                  <button class="action-btn" :disabled="syncingConn.has(c.id)" @click="handleSyncSchema(c.id)">
                    {{ syncingConn.has(c.id) ? '同步中...' : '同步' }}
                  </button>
                </template>
                <button v-if="c.has_schema" class="action-btn" @click="toggleSchemaView(c.id)">
                  {{ expandedSchemas.has(c.id) ? '收起' : 'Schema' }}
                </button>
                <button class="action-btn" @click="startEdit(c)">
                  <n-icon :component="CreateOutline" size="14" />
                </button>
                <button class="action-btn danger" @click="handleDelete(c.id, c.name)">
                  <n-icon :component="TrashOutline" size="14" />
                </button>
              </div>

              <div v-if="expandedSchemas.has(c.id)" class="schema-drawer">
                <div v-if="schemaLoading.has(c.id)" class="schema-loading">加载中...</div>
                <div v-else-if="!schemaCache.get(c.id)?.length" class="schema-empty">暂无表结构</div>
                <div v-else class="schema-tables">
                  <details v-for="t in schemaCache.get(c.id)" :key="t.table_name" class="schema-table">
                    <summary class="table-summary">
                      <span class="table-name">{{ t.table_name }}</span>
                      <span class="table-count">{{ t.columns.length }} 列</span>
                    </summary>
                    <div class="table-columns">
                      <span v-for="col in t.columns" :key="col" class="col-tag">{{ col }}</span>
                    </div>
                  </details>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- ── Admin ── -->
        <section v-if="activeTab === 'admin'" class="tab-panel">
          <div class="setting-card">
            <div class="card-label">
              <n-icon :component="KeyOutline" size="16" />
              <span>管理 Token</span>
            </div>
            <div class="admin-input-row">
              <n-input v-model:value="adminToken" placeholder="X-Admin-Token" type="password" :disabled="reindexLoading" />
            </div>
          </div>

          <div class="setting-card">
            <div class="card-label">
              <n-icon :component="RefreshOutline" size="16" />
              <span>重建向量索引</span>
            </div>
            <div class="admin-action-row">
              <n-button type="primary" :loading="reindexLoading" :disabled="!adminToken.trim()" @click="handleReindex">立即重建</n-button>
              <span class="admin-hint">需要 ADMIN_TOKEN 环境变量，未设置时 debug 模式自动放行</span>
            </div>
            <div v-if="reindexResult" class="admin-result">{{ reindexResult }}</div>
          </div>

          <div v-if="feedbackStats" class="setting-card">
            <div class="card-label">
              <n-icon :component="BarChartOutline" size="16" />
              <span>SQL 反馈统计</span>
            </div>
            <div class="feedback-grid">
              <div class="feedback-stat">
                <span class="feedback-value">{{ feedbackStats.total }}</span>
                <span class="feedback-label">总反馈</span>
              </div>
              <div class="feedback-stat">
                <span class="feedback-value" style="color: var(--success)">{{ feedbackStats.accepted }}</span>
                <span class="feedback-label">已接受</span>
              </div>
              <div class="feedback-stat">
                <span class="feedback-value" style="color: var(--warning)">{{ feedbackStats.modified }}</span>
                <span class="feedback-label">已修改</span>
              </div>
              <div class="feedback-stat">
                <span class="feedback-value" style="color: var(--error)">{{ feedbackStats.rejected }}</span>
                <span class="feedback-label">已拒绝</span>
              </div>
              <div class="feedback-stat">
                <span class="feedback-value" style="color: var(--accent)">{{ feedbackStats.enriched }}</span>
                <span class="feedback-label">已入库</span>
              </div>
              <div class="feedback-stat">
                <span class="feedback-value">{{ feedbackStats.pending }}</span>
                <span class="feedback-label">待处理</span>
              </div>
            </div>
            <n-button
              v-if="feedbackStats.pending > 0"
              size="small"
              type="primary"
              :loading="enrichLoading"
              style="margin-top: 16px; width: 100%"
              @click="handleEnrichFeedback"
            >
              将 {{ feedbackStats.pending }} 条反馈 enrich 到 Few-shot 库
            </n-button>
          </div>
        </section>
      </main>
    </div>
  </div>
</template>

<style scoped>
.settings-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ── Header ── */
.settings-header {
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

/* ── Body Layout ── */
.settings-body {
  flex: 1;
  display: flex;
  min-height: 0;
  overflow: hidden;
}

/* ── Left Nav ── */
.settings-nav {
  width: 200px;
  flex-shrink: 0;
  border-right: 1px solid var(--seam-1);
  background: var(--bg-void);
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 20px 12px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-radius: var(--radius-md);
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-2);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--duration-fast);
  text-align: left;
}
.nav-item:hover {
  background: var(--bg-hover);
  color: var(--text-1);
}
.nav-item.active {
  background: var(--bg-panel);
  color: var(--text-0);
  border-color: var(--seam-1);
  font-weight: 600;
}
.nav-item .n-icon {
  flex-shrink: 0;
  opacity: 0.6;
}
.nav-item.active .n-icon {
  opacity: 1;
}

/* ── Content ── */
.settings-main {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: 32px 40px 80px;
}

.tab-panel {
  animation: fadeInUp 0.25s var(--ease-out-expo) both;
  max-width: 760px;
}

/* ── Setting Card ── */
.setting-card {
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-lg);
  padding: 24px;
  margin-bottom: 16px;
  transition: border-color var(--duration-fast);
}
.setting-card:hover {
  border-color: var(--seam-2);
}

.card-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-0);
  margin-bottom: 16px;
}
.card-label .n-icon {
  color: var(--text-3);
}

.card-control {
  max-width: 360px;
}

/* ── Status Grid ── */
.status-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}
.status-cell {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  background: var(--bg-surface);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-md);
}
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.status-name {
  font-size: 13px;
  color: var(--text-2);
  flex: 1;
}
.status-value {
  font-size: 12px;
  font-weight: 600;
  font-family: var(--font-mono);
}
.status-empty {
  font-size: 13px;
  color: var(--text-3);
  padding: 8px 0;
}

/* ── Add Connection Button ── */
.add-connection-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  padding: 16px;
  border-radius: var(--radius-lg);
  border: 1px dashed var(--seam-2);
  background: transparent;
  color: var(--text-2);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  margin-bottom: 16px;
  transition: all var(--duration-fast);
}
.add-connection-btn:hover {
  border-color: var(--text-3);
  color: var(--text-0);
  background: var(--bg-hover);
}

/* ── Form Card ── */
.form-card {
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-lg);
  margin-bottom: 20px;
  overflow: hidden;
  animation: fadeInScale 0.25s var(--ease-out-expo) both;
}
.form-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--seam-1);
  background: var(--bg-surface);
}
.form-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-0);
}
.form-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  border: none;
  background: transparent;
  color: var(--text-3);
  cursor: pointer;
  transition: all var(--duration-fast);
}
.form-close:hover {
  background: var(--bg-hover);
  color: var(--text-0);
}
.form-body {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.form-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.form-field label {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-2);
  letter-spacing: 0.02em;
}
.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
@media (max-width: 480px) {
  .form-row { grid-template-columns: 1fr; }
}
.field-hint {
  font-size: 11px;
  color: var(--text-3);
  font-weight: normal;
  margin-left: 6px;
}
.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 4px;
}

/* ── Connection List ── */
.connection-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.connection-card {
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-lg);
  padding: 18px 20px;
  transition: all var(--duration-fast);
}
.connection-card:hover {
  border-color: var(--seam-2);
}

.conn-main {
  display: flex;
  align-items: center;
  gap: 14px;
}
.conn-icon-wrap {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-surface);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-md);
  color: var(--text-2);
  flex-shrink: 0;
}
.conn-info {
  flex: 1;
  min-width: 0;
}
.conn-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-0);
  display: block;
  margin-bottom: 6px;
}
.conn-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.conn-badge {
  font-size: 11px;
  font-weight: 500;
  padding: 3px 8px;
  border-radius: var(--radius-sm);
  background: var(--bg-surface);
  color: var(--text-2);
  border: 1px solid var(--seam-1);
}
.conn-badge.ok {
  background: rgba(22, 163, 74, 0.08);
  color: var(--success);
  border-color: rgba(22, 163, 74, 0.15);
}
.conn-badge.warn {
  background: rgba(217, 119, 6, 0.08);
  color: var(--warning);
  border-color: rgba(217, 119, 6, 0.15);
}
.conn-badge.muted {
  color: var(--text-3);
}
.conn-date {
  font-size: 12px;
  color: var(--text-3);
  margin-left: auto;
}

.conn-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--seam-1);
}
.action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 6px 12px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--seam-1);
  background: var(--bg-surface);
  color: var(--text-2);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--duration-fast);
}
.action-btn:hover:not(:disabled) {
  background: var(--bg-hover);
  color: var(--text-0);
  border-color: var(--seam-2);
}
.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.action-btn.danger:hover:not(:disabled) {
  color: var(--error);
  background: rgba(220, 38, 38, 0.06);
  border-color: rgba(220, 38, 38, 0.2);
}

/* ── Schema Drawer ── */
.schema-drawer {
  margin-top: 14px;
  padding: 14px;
  background: var(--bg-surface);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-md);
  animation: fadeIn 0.2s var(--ease-out-expo) both;
}
.schema-loading, .schema-empty {
  font-size: 12px;
  color: var(--text-3);
  text-align: center;
  padding: 12px 0;
}
.schema-tables {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.schema-table {
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-sm);
  overflow: hidden;
}
.table-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 12px;
  cursor: pointer;
  list-style: none;
  user-select: none;
  font-size: 13px;
  transition: background var(--duration-fast);
}
.table-summary:hover { background: var(--bg-hover); }
.table-summary::-webkit-details-marker { display: none; }
.table-name {
  font-weight: 600;
  color: var(--text-0);
  font-family: var(--font-mono);
  font-size: 12px;
}
.table-count {
  font-size: 11px;
  color: var(--text-3);
  font-family: var(--font-mono);
}
.table-columns {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px 12px 10px;
  border-top: 1px solid var(--seam-1);
}
.col-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--bg-surface);
  color: var(--text-2);
  border: 1px solid var(--seam-1);
  font-family: var(--font-mono);
}

/* ── Empty State ── */
.empty-state { padding: 48px 0; }

/* ── Admin ── */
.admin-input-row { max-width: 360px; }
.admin-action-row {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}
.admin-hint { font-size: 12px; color: var(--text-3); }
.admin-result {
  margin-top: 12px;
  padding: 10px 14px;
  background: var(--bg-surface);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-md);
  font-size: 12px;
  color: var(--text-2);
  font-family: var(--font-mono);
}

/* ── Feedback Grid ── */
.feedback-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}
@media (max-width: 600px) {
  .feedback-grid { grid-template-columns: repeat(2, 1fr); }
}
.feedback-stat {
  text-align: center;
  padding: 20px 12px;
  background: var(--bg-surface);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-md);
}
.feedback-value {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-0);
  font-family: var(--font-mono);
  line-height: 1;
}
.feedback-label {
  font-size: 12px;
  color: var(--text-3);
  margin-top: 6px;
}

@media (max-width: 768px) {
  .settings-header { padding: 10px 16px; }
  .settings-nav {
    width: 56px;
    padding: 12px 4px;
  }
  .nav-item span { display: none; }
  .nav-item { justify-content: center; padding: 10px 0; }
  .settings-main { padding: 16px; }
}
</style>
