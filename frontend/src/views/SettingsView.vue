<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { NInput, NButton, NSelect, NEmpty, NTag, useMessage, useDialog } from 'naive-ui'
import { useConnectionStore } from '@/stores/connection'
import { listConnections, createConnection, updateConnection, deleteConnection, getSchemaTables, type ConnectionCreate, type TableSchemaItem } from '@/api/connections'
import { listModels, type ModelInfo } from '@/api/models'
import { ArrowBackOutline, ServerOutline, TrashOutline, CreateOutline, RefreshOutline, CheckmarkCircleOutline, CloseCircleOutline, WarningOutline, ChevronDownOutline, ChevronUpOutline } from '@vicons/ionicons5'
import { NIcon } from 'naive-ui'
import { useRouter } from 'vue-router'
import { getHealthStatus, triggerReindex, type HealthStatus } from '@/api/admin'

const router = useRouter()
const connStore = useConnectionStore()
const naiveMsg = useMessage()
const dialog = useDialog()

const modelOptions = ref<{ label: string; value: string }[]>([])
const selectedModel = ref(localStorage.getItem('gbase_model') || 'deepseek/deepseek-chat')
watch(selectedModel, (val) => { localStorage.setItem('gbase_model', val) })

const showAddForm = ref(false)
const editingId = ref<string | null>(null)
const newConn = ref<ConnectionCreate & { id?: string }>({
  name: '', host: '', port: 5258, database_name: '', description: '', schema_ddl: '',
})
const connections = ref(connStore.connections)

// ── System status ──
const health = ref<HealthStatus | null>(null)
const healthLoading = ref(false)
const adminToken = ref('')
const reindexLoading = ref(false)
const reindexResult = ref<string | null>(null)

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
})

async function loadHealth() {
  healthLoading.value = true
  try {
    health.value = await getHealthStatus()
  } catch {
    // ignore
  } finally {
    healthLoading.value = false
  }
}

async function handleReindex() {
  if (!adminToken.value.trim()) {
    naiveMsg.warning('请输入管理 Token')
    return
  }
  reindexLoading.value = true
  reindexResult.value = null
  try {
    const resp = await triggerReindex(adminToken.value)
    const summary = Object.entries(resp.results)
      .map(([k, v]) => `${k}: ${v} 条`)
      .join('，')
    reindexResult.value = summary
    naiveMsg.success(`重建完成：${summary}`)
    await loadHealth()
  } catch (e: any) {
    const msg = e?.message || '重建失败'
    naiveMsg.error(msg)
    reindexResult.value = `失败：${msg}`
  } finally {
    reindexLoading.value = false
  }
}

const statusIcon = (s: string) => {
  if (s === 'connected' || s === 'ok') return CheckmarkCircleOutline
  if (s === 'degraded') return WarningOutline
  return CloseCircleOutline
}
const statusColor = (s: string) => {
  if (s === 'connected' || s === 'ok') return 'var(--success)'
  if (s === 'degraded') return 'var(--warning)'
  return 'var(--error)'
}
const statusLabel = (s: string) => {
  if (s === 'connected' || s === 'ok') return '正常'
  if (s === 'degraded') return '降级'
  if (s === 'disconnected') return '断开'
  if (s === 'unreachable') return '不可达'
  return s
}

// ── Schema browser ──
const expandedSchemas = ref<Set<string>>(new Set())
const schemaCache = ref<Map<string, TableSchemaItem[]>>(new Map())
const schemaLoading = ref<Set<string>>(new Set())

async function toggleSchemaView(connId: string) {
  if (expandedSchemas.value.has(connId)) {
    expandedSchemas.value.delete(connId)
    return
  }
  expandedSchemas.value.add(connId)
  if (!schemaCache.value.has(connId)) {
    schemaLoading.value.add(connId)
    try {
      const tables = await getSchemaTables(connId)
      schemaCache.value.set(connId, tables)
    } catch (e: any) {
      naiveMsg.error(e.message || '加载 Schema 失败')
      expandedSchemas.value.delete(connId)
    } finally {
      schemaLoading.value.delete(connId)
    }
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
    database_name: conn.database_name || '', description: conn.description || '', schema_ddl: conn.schema_ddl || '',
  }
  showAddForm.value = true
}

function resetForm() {
  editingId.value = null
  newConn.value = { name: '', host: '', port: 5258, database_name: '', description: '', schema_ddl: '' }
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
  <div class="settings-page">
    <div class="settings-inner">
      <!-- Back -->
      <button class="back-link" @click="router.push('/')">
        <n-icon :component="ArrowBackOutline" size="16" />
        <span>返回</span>
      </button>

      <h1 class="page-title">设置</h1>

      <!-- Model -->
      <section class="setting-section">
        <h2 class="section-title">模型</h2>
        <p class="section-desc">选择默认使用的 LLM 模型</p>
        <div class="control-wrap">
          <n-select v-model:value="selectedModel" :options="modelOptions" />
        </div>
      </section>

      <div class="divider" />

      <!-- System Status -->
      <section class="setting-section">
        <div class="section-header">
          <div>
            <h2 class="section-title">系统状态</h2>
            <p class="section-desc">后端服务与向量检索运行状态</p>
          </div>
          <n-button v-if="health" size="tiny" secondary @click="loadHealth">
            刷新
          </n-button>
        </div>

        <div class="status-card">
          <div v-if="healthLoading && !health" class="status-loading">
            加载中...
          </div>
          <template v-else-if="health">
            <div class="status-row">
              <span class="status-name">应用数据库</span>
              <span class="status-value" :style="{ color: statusColor(health.dependencies.database) }">
                <n-icon :component="statusIcon(health.dependencies.database)" size="14" />
                {{ statusLabel(health.dependencies.database) }}
              </span>
            </div>
            <div class="status-row">
              <span class="status-name">LLM API</span>
              <span class="status-value" :style="{ color: statusColor(health.dependencies.llm_api) }">
                <n-icon :component="statusIcon(health.dependencies.llm_api)" size="14" />
                {{ statusLabel(health.dependencies.llm_api) }}
              </span>
            </div>
            <div class="status-row">
              <span class="status-name">向量数据库</span>
              <span class="status-value" :style="{ color: statusColor(health.dependencies.vector_db) }">
                <n-icon :component="statusIcon(health.dependencies.vector_db)" size="14" />
                {{ statusLabel(health.dependencies.vector_db) }}
              </span>
            </div>
            <div class="status-row muted">
              <span class="status-name">默认模型</span>
              <span class="status-value" style="color: var(--text-muted)">{{ health.dependencies.default_model }}</span>
            </div>
          </template>
          <div v-else class="status-loading">状态获取失败</div>
        </div>

        <!-- Reindex -->
        <div class="reindex-block">
          <div class="reindex-row">
            <n-input
              v-model:value="adminToken"
              placeholder="管理 Token (X-Admin-Token)"
              size="small"
              :disabled="reindexLoading"
              type="password"
            />
            <n-button
              type="primary"
              size="small"
              :loading="reindexLoading"
              :disabled="!adminToken.trim()"
              @click="handleReindex"
            >
              <template #icon>
                <n-icon :component="RefreshOutline" />
              </template>
              重建向量索引
            </n-button>
          </div>
          <p class="reindex-hint">需要 ADMIN_TOKEN 环境变量，未设置时 debug 模式自动放行</p>
          <p v-if="reindexResult" class="reindex-result">{{ reindexResult }}</p>
        </div>
      </section>

      <div class="divider" />

      <!-- Connections -->
      <section class="setting-section">
        <div class="section-header">
          <div>
            <h2 class="section-title">数据库连接</h2>
            <p class="section-desc">管理 GBase 8a 数据库连接与 Schema</p>
          </div>
          <n-button type="primary" size="small" @click="showAddForm = !showAddForm">
            {{ showAddForm ? '取消' : '添加连接' }}
          </n-button>
        </div>

        <!-- Form -->
        <div v-if="showAddForm" class="form-card">
          <div class="form-fields">
            <div class="field">
              <label>连接名称 *</label>
              <n-input v-model:value="newConn.name" placeholder="生产环境" />
            </div>
            <div class="field-row">
              <div class="field">
                <label>主机地址</label>
                <n-input v-model:value="newConn.host" placeholder="localhost" />
              </div>
              <div class="field">
                <label>数据库名</label>
                <n-input v-model:value="newConn.database_name" placeholder="gbase_db" />
              </div>
            </div>
            <div class="field">
              <label>Schema DDL</label>
              <n-input v-model:value="newConn.schema_ddl" type="textarea" placeholder="粘贴 CREATE TABLE 语句..." :autosize="{ minRows: 4, maxRows: 10 }" />
            </div>
            <n-button v-if="editingId" type="primary" @click="handleUpdate">更新连接</n-button>
            <n-button v-else type="primary" @click="handleCreate">保存连接</n-button>
          </div>
        </div>

        <!-- List -->
        <div v-if="connections.length === 0" class="empty-wrap">
          <n-empty description="暂无数据库连接" />
        </div>
        <div v-else class="conn-list">
          <div v-for="c in connections" :key="c.id" class="conn-wrap">
            <div class="conn-row">
              <div class="conn-main">
                <n-icon :component="ServerOutline" size="18" class="conn-icon" />
                <div class="conn-info">
                  <span class="conn-name">{{ c.name }}</span>
                  <div class="conn-meta">
                    <n-tag v-if="c.has_schema" size="small" type="success">已配置 Schema</n-tag>
                    <n-tag v-else size="small" type="default">无 Schema</n-tag>
                    <span class="conn-time">{{ new Date(c.created_at).toLocaleDateString() }}</span>
                  </div>
                </div>
              </div>
              <div class="conn-actions">
                <button v-if="c.has_schema" class="action-btn schema-toggle" :class="{ active: expandedSchemas.has(c.id) }" @click="toggleSchemaView(c.id)">
                  <n-icon :component="expandedSchemas.has(c.id) ? ChevronUpOutline : ChevronDownOutline" size="15" />
                </button>
                <button class="action-btn" @click="startEdit(c)">
                  <n-icon :component="CreateOutline" size="15" />
                </button>
                <button class="action-btn danger" @click="handleDelete(c.id, c.name)">
                  <n-icon :component="TrashOutline" size="15" />
                </button>
              </div>
            </div>

            <!-- Schema panel -->
            <div v-if="expandedSchemas.has(c.id)" class="schema-panel">
              <div v-if="schemaLoading.has(c.id)" class="schema-loading">加载中...</div>
              <div v-else-if="!schemaCache.get(c.id)?.length" class="schema-empty">暂无表结构</div>
              <div v-else class="schema-tables">
                <details v-for="t in schemaCache.get(c.id)" :key="t.table_name" class="schema-table-item">
                  <summary class="table-summary">
                    <span class="table-name">{{ t.table_name }}</span>
                    <span class="table-col-count">{{ t.columns.length }} 列</span>
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
    </div>
  </div>
</template>

<style scoped>
.settings-page {
  height: 100%;
  overflow-y: auto;
  background: var(--bg-body);
  animation: fadeInUp var(--duration-slow) var(--ease-out-expo) both;
}
.settings-inner {
  max-width: 560px;
  margin: 0 auto;
  padding: 48px 24px 80px;
}
@media (max-width: 768px) {
  .settings-inner { padding: 32px 20px 60px; }
}

.back-link {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 14px; color: var(--text-secondary);
  background: none; border: none; cursor: pointer;
  margin-bottom: 20px;
  transition: color var(--duration-fast) var(--ease-smooth);
}
.back-link:hover { color: var(--text-primary); }

.page-title {
  font-size: var(--text-2xl); font-weight: 600;
  color: var(--text-primary); letter-spacing: -0.03em;
  margin-bottom: 32px;
}

.setting-section { margin-bottom: 8px; }
.section-header {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 12px; margin-bottom: 20px;
}
.section-title {
  font-size: var(--text-lg); font-weight: 600;
  color: var(--text-primary); letter-spacing: -0.02em;
  margin-bottom: 4px;
}
.section-desc {
  font-size: 13px; color: var(--text-secondary);
}
.control-wrap { max-width: 320px; margin-top: 12px; }

.divider {
  height: 1px; background: var(--divider);
  margin: 28px 0;
}

/* Form */
.form-card {
  background: var(--bg-surface);
  backdrop-filter: blur(16px);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 20px 22px;
  margin-bottom: 20px;
  box-shadow: var(--shadow-sm);
}
.form-fields { display: flex; flex-direction: column; gap: 16px; }
.field { display: flex; flex-direction: column; gap: 6px; }
.field label {
  font-size: 12px; font-weight: 500;
  color: var(--text-secondary); letter-spacing: 0.02em;
}
.field-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
@media (max-width: 480px) { .field-row { grid-template-columns: 1fr; } }

/* Connection list */
.conn-list { display: flex; flex-direction: column; gap: 2px; }
.conn-row {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; padding: 12px 14px;
  border-radius: var(--radius-md);
  transition: background var(--duration-fast) var(--ease-smooth);
}
.conn-row:hover { background: var(--bg-hover); }

.conn-main {
  display: flex; align-items: center; gap: 12px;
  flex: 1; min-width: 0;
}
.conn-icon { color: var(--text-muted); flex-shrink: 0; }
.conn-info { flex: 1; min-width: 0; }
.conn-name {
  font-size: 14px; font-weight: 500;
  color: var(--text-primary); display: block;
  margin-bottom: 4px;
}
.conn-meta {
  display: flex; align-items: center; gap: 8px;
}
.conn-time {
  font-size: 12px; color: var(--text-muted);
}

.conn-actions {
  display: flex; align-items: center; gap: 2px;
  opacity: 0;
  transition: opacity var(--duration-fast) var(--ease-smooth);
}
.conn-row:hover .conn-actions { opacity: 1; }

.action-btn {
  display: flex; align-items: center; justify-content: center;
  width: 30px; height: 30px; padding: 0;
  background: none; border: none; border-radius: 7px;
  color: var(--text-muted); cursor: pointer;
  transition: all var(--duration-fast) var(--ease-smooth);
}
.action-btn:hover { background: var(--bg-active); color: var(--text-primary); }
.action-btn.danger:hover { color: var(--error); background: rgba(255,59,48,0.1); }

.empty-wrap { padding: 32px 0; }

/* Status card */
.status-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 16px 20px;
  margin-bottom: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.status-loading {
  font-size: 13px;
  color: var(--text-secondary);
  text-align: center;
  padding: 8px 0;
}
.status-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
  padding: 4px 0;
}
.status-row.muted { opacity: 0.7; }
.status-name {
  color: var(--text-secondary);
  font-weight: 500;
}
.status-value {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-family: var(--font-mono);
}

/* Reindex block */
.reindex-block {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 16px 20px;
}
.reindex-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.reindex-row :deep(.n-input) { flex: 1; min-width: 0; }
.reindex-hint {
  font-size: 11px;
  color: var(--text-muted);
  margin: 8px 0 0;
  font-family: var(--font-mono);
}
.reindex-result {
  font-size: 12px;
  color: var(--text-secondary);
  margin: 8px 0 0;
  font-family: var(--font-mono);
  padding: 8px 10px;
  background: var(--bg-surface);
  border-radius: var(--radius-sm);
  border: 1px solid var(--seam-1);
}

/* Schema panel */
.conn-wrap { display: flex; flex-direction: column; }
.schema-toggle { color: var(--text-muted); }
.schema-toggle.active { color: var(--accent); }
.schema-panel {
  margin: 0 14px 8px;
  padding: 10px 14px;
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-md);
  animation: fadeIn 0.2s var(--ease-out-expo) both;
}
.schema-loading, .schema-empty {
  font-size: 12px;
  color: var(--text-muted);
  padding: 8px 0;
  text-align: center;
}
.schema-tables {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.schema-table-item {
  background: var(--bg-surface);
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
  color: var(--text-primary);
  font-family: var(--font-mono);
}
.table-col-count {
  font-size: 11px;
  color: var(--text-muted);
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
  background: var(--bg-panel);
  color: var(--text-secondary);
  border: 1px solid var(--seam-1);
  font-family: var(--font-mono);
}
</style>
