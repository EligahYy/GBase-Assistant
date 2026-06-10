<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { NInput, NButton, NSelect, NEmpty, useMessage, useDialog } from 'naive-ui'
import { useConnectionStore } from '@/stores/connection'
import { listConnections, createConnection, updateConnection, deleteConnection, getSchemaTables, testConnection, syncSchema, type ConnectionCreate, type TableSchemaItem } from '@/api/connections'
import { listModels, type ModelInfo } from '@/api/models'
import {
  ArrowBackOutline, ServerOutline, TrashOutline, CreateOutline, RefreshOutline,
  CubeOutline, PulseOutline, BarChartOutline, LayersOutline, AddOutline, CloseOutline,
  SunnyOutline, SparklesOutline,
} from '@vicons/ionicons5'
import { NIcon } from 'naive-ui'
import { useRouter } from 'vue-router'
import { getHealthStatus, getFeedbackStats, type HealthStatus, type FeedbackStats } from '@/api/admin'

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
  { label: 'SQLite 本地开发', value: 'sqlite' },
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

// ── Feedback stats ──
const feedbackStats = ref<FeedbackStats | null>(null)
const feedbackLoading = ref(false)

// ── Connection actions ──
const testingConn = ref<Set<string>>(new Set())
const syncingConn = ref<Set<string>>(new Set())

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
  await loadFeedbackStats()
  connStore.startStatusStream()
})

async function loadFeedbackStats() {
  feedbackLoading.value = true
  try {
    feedbackStats.value = await getFeedbackStats('123456')
  } catch {
    feedbackStats.value = null
  } finally {
    feedbackLoading.value = false
  }
}


const expandedSchemas = ref<Set<string>>(new Set())
const schemaCache = ref<Map<string, TableSchemaItem[]>>(new Map())
const schemaLoading = ref<Set<string>>(new Set())

async function loadHealth() {
  healthLoading.value = true
  try { health.value = await getHealthStatus() } catch { /* ignore */ } finally { healthLoading.value = false }
}


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
    connStore.setLocalStatus(connId, resp.status === 'ok' ? 'ok' : 'error')
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

</script>

<template>
  <div class="page-shell settings-page">
    <!-- Header -->
    <header class="settings-header">
      <button class="back-btn" @click="router.push('/')">
        <n-icon :component="ArrowBackOutline" size="16" />
        <span>返回</span>
      </button>
      <span class="header-title">设置</span>
    </header>

    <!-- Body -->
    <div class="settings-body">
      <main class="settings-main">
        <h1 class="settings-page-title">系统设置</h1>

        <!-- ── General ── -->
        <section class="tab-panel">
          <div class="section-label">通用设置</div>

          <!-- Theme item card -->
          <div class="item-card">
            <div class="item-left">
              <div class="item-icon">
                <n-icon :component="SunnyOutline" size="18" />
              </div>
              <div>
                <div class="item-title">外观主题</div>
                <div class="item-status">当前：浅色模式</div>
              </div>
            </div>
            <div class="theme-toggle">
              <button class="toggle-option active">浅色</button>
              <button class="toggle-option">深色</button>
            </div>
          </div>

          <!-- Model item card -->
          <div class="item-card">
            <div class="item-left">
              <div class="item-icon" style="background:#f5f3ff;border-color:#ddd6fe;">
                <n-icon :component="SparklesOutline" size="18" color="#7c3aed" />
              </div>
              <div>
                <div class="item-title">默认模型</div>
                <div class="item-status">
                  当前：<code>deepseek-chat</code>
                  <span class="status-indicator ok">可用</span>
                </div>
              </div>
            </div>
            <n-select v-model:value="selectedModel" :options="modelOptions" style="width:200px;" size="small" />
          </div>

          <!-- System Status -->
          <div class="section-label" style="margin-top:28px;">系统状态</div>
          <div class="status-grid">
            <template v-if="health">
              <div
                v-for="(value, key) in health.dependencies"
                v-show="key !== 'default_model'"
                :key="key"
                class="status-cell"
              >
                <div class="status-dot" :style="{ background: statusColor(value, key) }" />
                <span class="status-name">{{ { database: 'SQLite 数据库', llm_api: 'LLM API', vector_db: 'Qdrant 向量库', default_model: '', gbase_connections: 'GBase 连接' }[key] || key }}</span>
                <span class="status-value" :style="{ color: statusColor(value, key) }">{{ statusLabel(value, key) }}</span>
              </div>
            </template>
            <div v-else-if="healthLoading" class="status-empty">加载中...</div>
            <div v-else class="status-empty">状态获取失败</div>
          </div>
        </section>

        <!-- ── Connections ── -->
        <section class="tab-panel">
          <div class="section-label">数据库连接</div>
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
                  <n-input v-model:value="newConn.database_name" :placeholder="newConn.driver_type === 'sqlite' ? 'data/nl2sql_demo.db' : 'gbase_db'" />
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
              <div class="conn-top">
                <div class="conn-main">
                  <div
                    class="conn-icon-wrap"
                    :class="{
                      'conn-ok': connStore.connStatusMap[c.id] === 'ok',
                      'conn-err': connStore.connStatusMap[c.id] === 'error',
                    }"
                  >
                    <n-icon :component="ServerOutline" size="18" />
                  </div>
                  <div class="conn-info">
                    <span class="conn-name">{{ c.name }}</span>
                    <div class="conn-detail">
                      <template v-if="c.host">{{ c.host }}:{{ c.port }}</template>
                      <template v-else-if="c.driver_type === 'sqlite'">本地 SQLite</template>
                      <template v-else>手动模式</template>
                    </div>
                    <div class="conn-meta">
                      <span :class="['conn-badge', c.has_schema ? 'ok' : 'muted']">{{ c.has_schema ? '已配置 Schema' : '无 Schema' }}</span>
                      <span class="conn-badge">{{ c.driver_type === 'manual' ? '手动' : c.driver_type === 'sqlite' ? 'SQLite' : '原生驱动' }}</span>
                    </div>
                  </div>
                </div>
                <div v-if="c.driver_type !== 'manual'" class="conn-status-badge" :class="connStore.connStatusMap[c.id] === 'ok' ? 'ok' : connStore.connStatusMap[c.id] === 'error' ? 'err' : ''">
                  <span class="conn-status-dot" :class="connStore.connStatusMap[c.id] === 'ok' ? 'ok' : connStore.connStatusMap[c.id] === 'error' ? 'err' : ''"></span>
                  {{ connStore.connStatusMap[c.id] === 'ok' ? '已连接' : connStore.connStatusMap[c.id] === 'error' ? '连接失败' : '待检测' }}
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
        <section class="tab-panel">
          <div class="section-label" style="margin-top:28px;">SQL 反馈统计</div>
          <div v-if="feedbackStats" class="feedback-grid">
            <div class="feedback-stat">
              <span class="feedback-value">{{ feedbackStats.total }}</span>
              <span class="feedback-label">总反馈</span>
            </div>
            <div class="feedback-stat accepted">
              <span class="feedback-value">{{ feedbackStats.accepted }}</span>
              <span class="feedback-label">已接受</span>
            </div>
            <div class="feedback-stat modified">
              <span class="feedback-value">{{ feedbackStats.modified }}</span>
              <span class="feedback-label">已修改</span>
            </div>
            <div class="feedback-stat rejected">
              <span class="feedback-value">{{ feedbackStats.rejected }}</span>
              <span class="feedback-label">已拒绝</span>
            </div>
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
  background: #fafafa;
}

/* ── Header ── */
.settings-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 0 24px;
  height: 48px;
  border-bottom: 1px solid #eee;
  background: #fff;
  flex-shrink: 0;
}

.settings-body {
  flex: 1;
  overflow-y: auto;
}

.settings-main {
  max-width: 640px;
  margin: 0 auto;
  padding: 36px 24px 80px;
}

.back-btn {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 13px; color: var(--text-3);
  background: var(--bg-panel); border: 1px solid var(--seam-1);
  border-radius: var(--radius-md); padding: 5px 10px;
  cursor: pointer; transition: all var(--duration-fast);
}
.back-btn:hover { color: var(--text-0); border-color: var(--seam-2); }
.header-title { font-size: 15px; font-weight: 600; color: #111; }

.tab-panel {
  animation: fadeInUp 0.25s var(--ease-out-expo) both;
  max-width: 760px;
}

.settings-page-title {
  font-size: 24px;
  font-weight: 700;
  color: #111;
  letter-spacing: -0.02em;
  margin-bottom: 28px;
}

.section-label {
  font-size: 10px;
  font-weight: 700;
  color: #bbb;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 10px;
  padding: 0 2px;
}

/* ── Item Card ── */
.item-card {
  display: flex; align-items: center; justify-content: space-between;
  background: #fff; border: 1px solid #eee;
  border-radius: 12px; padding: 14px 16px; margin-bottom: 6px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.03);
}
.item-left { display: flex; align-items: flex-start; gap: 12px; }
.item-icon {
  width: 36px; height: 36px;
  background: #f9f9f9; border: 1px solid #eee;
  border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  color: #888; flex-shrink: 0;
}
.item-title { font-size: 13px; font-weight: 600; color: #111; margin-bottom: 2px; }
.item-status { font-size: 10px; color: #aaa; }
.item-status code { color: #111; font-family: monospace; font-weight: 500; background:#f5f5f5; padding:1px 4px; border-radius:3px; }
.status-indicator { display: inline-flex; align-items: center; gap: 3px; margin-left: 6px; font-size: 10px; font-weight: 500; }
.status-indicator.ok { color: #16a34a; }
.status-indicator::before { content: ''; width: 5px; height: 5px; background: currentColor; border-radius: 50%; }

/* ── Theme Toggle ── */
.theme-toggle { display: flex; background: #f4f4f4; border-radius: 8px; padding: 2px; }
.toggle-option {
  padding: 5px 14px; font-size: 11px; font-weight: 500;
  border: none; background: transparent; color: #aaa;
  border-radius: 6px; cursor: pointer; transition: all 0.15s;
}
.toggle-option.active { background: #fff; color: #111; font-weight: 600; box-shadow: 0 1px 1px rgba(0,0,0,0.04); }

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
  grid-template-columns: 1fr 1fr;
  gap: 8px;
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

.conn-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}
.conn-main {
  display: flex;
  align-items: flex-start;
  gap: 14px;
}
.conn-icon-wrap {
  width: 40px; height: 40px;
  display: flex; align-items: center; justify-content: center;
  background: #f5f5f5; border: 1px solid #e8e8e8;
  border-radius: 12px; color: #999; flex-shrink: 0;
}
.conn-icon-wrap.conn-ok {
  background: #ecfdf5; border-color: #bbf7d0; color: #16a34a;
}
.conn-icon-wrap.conn-err {
  background: #fef2f2; border-color: #fecaca; color: #dc2626;
}
.conn-info {
  flex: 1;
  min-width: 0;
}
.conn-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-0);
  display: block;
  margin-bottom: 3px;
}
.conn-detail {
  font-size: 11px; color: #999; font-family: var(--font-mono);
  margin-bottom: 4px; display: flex; align-items: center;
}
.conn-status-dot {
  width: 5px; height: 5px; border-radius: 50%;
  background: #ccc; display: inline-block; margin-right: 4px;
}
.conn-status-dot.ok { background: #16a34a; }
.conn-status-dot.err { background: #dc2626; }

.conn-status-badge {
  display: flex; align-items: center; gap: 6px;
  font-size: 10px; font-weight: 600;
  padding: 3px 10px; border-radius: 6px;
  background: #f5f5f5; color: #999; border: 1px solid #e8e8e8;
  flex-shrink: 0;
}
.conn-status-badge.ok { background: #ecfdf5; color: #16a34a; border-color: #bbf7d0; }
.conn-status-badge.err { background: #fef2f2; color: #dc2626; border-color: #fecaca; }

.conn-actions { display: flex; align-items: center; gap: 4px; margin-top: 12px; padding-top: 12px; border-top: 1px solid #eee; flex-wrap: wrap; }
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
  padding: 16px 10px;
  background: #fafafa;
  border: 1px solid #eee;
  border-radius: 10px;
}
.feedback-stat.accepted { background: #ecfdf5; border-color: #bbf7d0; }
.feedback-stat.modified { background: #fef7ed; border-color: #fde68a; }
.feedback-stat.rejected { background: #fef2f2; border-color: #fecaca; }
.feedback-value {
  font-size: 22px;
  font-weight: 700;
  color: #111;
  font-family: var(--font-mono);
  line-height: 1;
}
.feedback-stat.accepted .feedback-value { color: #16a34a; }
.feedback-stat.modified .feedback-value { color: #d97706; }
.feedback-stat.rejected .feedback-value { color: #dc2626; }
.feedback-label {
  font-size: 11px;
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
