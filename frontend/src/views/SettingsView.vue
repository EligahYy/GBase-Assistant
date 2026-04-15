<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  NInput,
  NButton,
  NSelect,
  NCard,
  NEmpty,
  NSpace,
  NTag,
  useMessage,
  useDialog,
} from 'naive-ui'
import { useConnectionStore } from '@/stores/connection'
import { listConnections, createConnection, deleteConnection, type ConnectionCreate } from '@/api/connections'
import { ArrowBackOutline, ServerOutline, TrashOutline } from '@vicons/ionicons5'
import { NIcon } from 'naive-ui'
import { useRouter } from 'vue-router'

const router = useRouter()
const connStore = useConnectionStore()
const naiveMsg = useMessage()
const dialog = useDialog()

const modelOptions = [
  { label: 'DeepSeek Coder', value: 'deepseek/deepseek-coder' },
  { label: 'DeepSeek Chat', value: 'deepseek/deepseek-chat' },
  { label: 'Qwen 2.5 Coder 32B', value: 'qwen/qwen2.5-coder-32b-instruct' },
  { label: 'GPT-4o', value: 'openai/gpt-4o' },
]
const selectedModel = ref('deepseek/deepseek-chat')

const showAddForm = ref(false)
const newConn = ref<ConnectionCreate>({
  name: '',
  host: '',
  port: 5258,
  database_name: '',
  description: '',
  schema_ddl: '',
})
const connections = ref(connStore.connections)

onMounted(async () => {
  connections.value = await listConnections()
})

async function handleCreate() {
  if (!newConn.value.name.trim()) {
    naiveMsg.error('请输入连接名称')
    return
  }
  try {
    await createConnection(newConn.value)
    naiveMsg.success('连接已创建')
    newConn.value = { name: '', host: '', port: 5258, database_name: '', description: '', schema_ddl: '' }
    showAddForm.value = false
    connections.value = await listConnections()
    await connStore.loadConnections()
  } catch (e: any) {
    naiveMsg.error(e.message || '创建失败')
  }
}

function handleDelete(id: string, name: string) {
  dialog.warning({
    title: '删除连接',
    content: `确定删除数据库连接「${name}」？`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await deleteConnection(id)
        naiveMsg.success(`已删除 ${name}`)
        connections.value = await listConnections()
        await connStore.loadConnections()
      } catch (e: any) {
        naiveMsg.error(e.message || '删除失败')
      }
    },
  })
}
</script>

<template>
  <div class="settings-page">
    <header class="settings-header">
      <button class="back-btn" @click="router.push('/')">
        <n-icon :component="ArrowBackOutline" size="18" />
      </button>
      <h1 class="title">设置</h1>
    </header>

    <div class="settings-body">
      <div class="settings-body-inner">
        <!-- Model Settings -->
        <div class="setting-card">
          <h2 class="setting-card-title">模型配置</h2>
          <p class="setting-card-desc">选择默认使用的 LLM 模型</p>
          <div class="control-row">
            <n-select v-model:value="selectedModel" :options="modelOptions" />
          </div>
        </div>

        <!-- Connections -->
        <div class="setting-card">
          <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 14px;">
            <div>
              <h2 class="setting-card-title">数据库连接</h2>
              <p class="setting-card-desc">管理 GBase 8a 数据库连接与 Schema</p>
            </div>
            <n-button type="primary" size="small" @click="showAddForm = !showAddForm">
              {{ showAddForm ? '取消' : '添加连接' }}
            </n-button>
          </div>

          <!-- Add Form -->
          <div v-if="showAddForm" class="add-form">
            <n-space vertical :size="12">
              <n-input v-model:value="newConn.name" placeholder="连接名称 *" />
              <n-input v-model:value="newConn.host" placeholder="主机地址" />
              <n-input v-model:value="newConn.database_name" placeholder="数据库名" />
              <n-input
                v-model:value="newConn.schema_ddl"
                type="textarea"
                placeholder="粘贴 Schema DDL（可选）"
                :autosize="{ minRows: 4, maxRows: 10 }"
              />
              <n-button type="primary" @click="handleCreate">保存连接</n-button>
            </n-space>
          </div>

          <!-- Connection List -->
          <div v-if="connections.length === 0" class="empty-wrap">
            <n-empty description="暂无数据库连接" />
          </div>
          <div v-else class="conn-grid">
            <div
              v-for="c in connections"
              :key="c.id"
              class="conn-card"
            >
              <div class="conn-row">
                <div class="conn-info">
                  <div class="conn-name">
                    <n-icon :component="ServerOutline" size="16" />
                    <span>{{ c.name }}</span>
                  </div>
                  <div class="conn-meta">
                    <n-tag v-if="c.has_schema" size="small" type="success">已配置 Schema</n-tag>
                    <n-tag v-else size="small" type="default">无 Schema</n-tag>
                    <span class="conn-time">{{ new Date(c.created_at).toLocaleString() }}</span>
                  </div>
                </div>
                <button class="icon-btn danger" @click="handleDelete(c.id, c.name)">
                  <n-icon :component="TrashOutline" size="16" />
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--bg-body);
}

.settings-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 20px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-primary);
  flex-shrink: 0;
}
.back-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: none;
  border-radius: var(--radius-md);
  background: var(--bg-secondary);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}
.back-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}
.title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
}

.settings-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 24px 20px 80px;
}
.settings-body-inner {
  max-width: 720px;
  margin: 0 auto;
}

.setting-card {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  padding: 20px 22px;
  margin-bottom: 20px;
}
.setting-card-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 4px;
}
.setting-card-desc {
  font-size: 13px;
  color: var(--text-muted);
  margin-bottom: 14px;
}

.control-row {
  max-width: 360px;
}

.add-form {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 16px 18px;
  margin-bottom: 16px;
}

.empty-wrap {
  padding: 40px 0;
}

.conn-grid {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.conn-card {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 14px 16px;
  transition: box-shadow 0.15s ease, border-color 0.15s ease;
}
.conn-card:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-md);
}
.conn-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.conn-name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  margin-bottom: 6px;
}
.conn-meta {
  display: flex;
  align-items: center;
  gap: 10px;
}
.conn-time {
  font-size: 12px;
  color: var(--text-tertiary);
}

.icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.12s ease;
}
.icon-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}
.icon-btn.danger:hover {
  background: rgba(239, 68, 68, 0.12);
  color: var(--error);
}
</style>
