<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { NInput, NButton, NSelect, NEmpty, NTag, useMessage, useDialog } from 'naive-ui'
import { useConnectionStore } from '@/stores/connection'
import { listConnections, createConnection, updateConnection, deleteConnection, type ConnectionCreate } from '@/api/connections'
import { listModels, type ModelInfo } from '@/api/models'
import { ArrowBackOutline, ServerOutline, TrashOutline, CreateOutline } from '@vicons/ionicons5'
import { NIcon } from 'naive-ui'
import { useRouter } from 'vue-router'

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

onMounted(async () => {
  connections.value = await listConnections()
  try {
    const models = await listModels()
    modelOptions.value = models.map((m: ModelInfo) => ({ label: m.name, value: m.id }))
  } catch {
    modelOptions.value = [
      { label: 'DeepSeek Chat', value: 'deepseek/deepseek-chat' },
      { label: 'DeepSeek Coder', value: 'deepseek/deepseek-coder' },
      { label: 'Qwen 2.5 Coder 32B', value: 'qwen/qwen2.5-coder-32b-instruct' },
      { label: 'GPT-4o', value: 'openai/gpt-4o' },
    ]
  }
})

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
          <div v-for="c in connections" :key="c.id" class="conn-row">
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
              <button class="action-btn" @click="startEdit(c)">
                <n-icon :component="CreateOutline" size="15" />
              </button>
              <button class="action-btn danger" @click="handleDelete(c.id, c.name)">
                <n-icon :component="TrashOutline" size="15" />
              </button>
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
</style>
