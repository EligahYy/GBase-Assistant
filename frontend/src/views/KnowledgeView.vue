<script setup lang="ts">
import { ref, onMounted, onUnmounted, h } from 'vue'
import {
  NCard, NDataTable, NUpload, NButton, NTag, NProgress,
  NIcon, NSpace, NModal, useMessage,
  type DataTableColumn, type UploadFileInfo,
} from 'naive-ui'
import { TrashOutline, RefreshOutline, CloudUploadOutline } from '@vicons/ionicons5'
import {
  fetchDocuments, uploadDocument, deleteDocument, reindexDocument,
  reindexAll, fetchIndexState, getProgressSSEUrl,
  type KnowledgeDocument, type IndexStateResponse,
} from '@/api/knowledge'

defineOptions({ name: 'KnowledgeView' })

const msg = useMessage()
const documents = ref<KnowledgeDocument[]>([])
const total = ref(0)
const indexState = ref<IndexStateResponse>({ total_documents: 0, total_chunks: 0, ready_documents: 0, last_indexed_at: null })
const loading = ref(false)
const showReindexAllModal = ref(false)
const progressMap = ref<Record<string, { phase: string; indexed: number; total: number }>>({})
const eventSources: Record<string, EventSource> = {}

function statusTag(status: string) {
  const map: Record<string, { type: 'default' | 'info' | 'success' | 'warning' | 'error'; label: string }> = {
    pending:   { type: 'default',  label: '等待中' },
    parsing:   { type: 'info',     label: '解析中' },
    chunking:  { type: 'info',     label: '切片中' },
    indexing:  { type: 'info',     label: '索引中' },
    ready:     { type: 'success',  label: '就绪' },
    error:     { type: 'error',    label: '失败' },
  }
  return map[status] || { type: 'default', label: status }
}

function fileTypeTag(type: string) {
  return type === 'pdf' ? { type: 'error' as const, label: 'PDF' } : { type: 'info' as const, label: 'MD' }
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatTime(iso: string | null) {
  if (!iso) return '-'
  const d = new Date(iso)
  return d.toLocaleString('zh-CN')
}

function connectProgress(docId: string) {
  if (eventSources[docId]) return
  const url = getProgressSSEUrl(docId)
  const es = new EventSource(url)
  es.onmessage = (e) => {
    try {
      const { event, data } = JSON.parse(e.data)
      if (event === 'progress') {
        progressMap.value[docId] = {
          phase: data.phase || '',
          indexed: (data.indexed as number) || 0,
          total: (data.total as number) || 0,
        }
      } else if (event === 'complete') {
        delete progressMap.value[docId]
        es.close()
        delete eventSources[docId]
        load()
      } else if (event === 'error') {
        delete progressMap.value[docId]
        es.close()
        delete eventSources[docId]
        load()
      }
    } catch {}
  }
  es.onerror = () => {
    es.close()
    delete eventSources[docId]
  }
  eventSources[docId] = es
}

async function load() {
  loading.value = true
  try {
    const [docsRes, stateRes] = await Promise.all([fetchDocuments({}), fetchIndexState()])
    documents.value = docsRes.documents
    total.value = docsRes.total
    indexState.value = stateRes
    for (const d of docsRes.documents) {
      if (['pending', 'parsing', 'chunking', 'indexing'].includes(d.status)) {
        connectProgress(d.id)
      }
    }
  } catch (e: any) {
    msg.error(e.message || '加载失败')
  } finally {
    loading.value = false
  }
}

async function handleUpload(options: { file: UploadFileInfo; onFinish: () => void; onError: () => void }) {
  if (!options.file.file) return
  try {
    const doc = await uploadDocument(options.file.file)
    documents.value.unshift(doc)
    total.value++
    connectProgress(doc.id)
    msg.success(`${options.file.name} 上传成功，开始索引`)
    options.onFinish()
  } catch (e: any) {
    msg.error(e.message || '上传失败')
    options.onError()
  }
}

async function remove(doc: KnowledgeDocument) {
  try {
    await deleteDocument(doc.id)
    documents.value = documents.value.filter(d => d.id !== doc.id)
    total.value--
    if (eventSources[doc.id]) {
      eventSources[doc.id].close()
      delete eventSources[doc.id]
    }
    delete progressMap.value[doc.id]
    msg.success('已删除')
  } catch (e: any) {
    msg.error(e.message || '删除失败')
  }
}

async function reindex(doc: KnowledgeDocument) {
  try {
    await reindexDocument(doc.id)
    doc.status = 'pending'
    doc.error_message = null
    connectProgress(doc.id)
    msg.success('已触发重新索引')
  } catch (e: any) {
    msg.error(e.message || '重新索引失败')
  }
}

async function handleReindexAll() {
  try {
    await reindexAll()
    showReindexAllModal.value = false
    msg.success('全量重建已触发')
    load()
  } catch (e: any) {
    msg.error(e.message || '失败')
  }
}

onMounted(load)
onUnmounted(() => {
  Object.values(eventSources).forEach(es => es.close())
})

const columns: DataTableColumn<KnowledgeDocument>[] = [
  { title: '文件名', key: 'filename', ellipsis: { tooltip: true }, width: 300 },
  {
    title: '类型', key: 'file_type', width: 80,
    render(row) {
      const t = fileTypeTag(row.file_type)
      return h(NTag, { type: t.type, size: 'small', bordered: false }, { default: () => t.label })
    },
  },
  { title: '大小', key: 'file_size', width: 100, render(row) { return formatSize(row.file_size) } },
  {
    title: '状态', key: 'status', width: 100,
    render(row) {
      const t = statusTag(row.status)
      return h(NTag, { type: t.type, size: 'small', bordered: false }, { default: () => t.label })
    },
  },
  { title: '分块数', key: 'chunk_count', width: 80, render(row) { return row.chunk_count || '-' } },
  { title: '索引时间', key: 'indexed_at', width: 170, render(row) { return formatTime(row.indexed_at) } },
  {
    title: '操作', key: 'actions', width: 120,
    render(row) {
      return h(NSpace, { size: 'small' }, {
        default: () => [
          h(NButton, { size: 'tiny', quaternary: true, onClick: () => reindex(row) },
            { icon: () => h(NIcon, null, { default: () => h(RefreshOutline) }) }),
          h(NButton, { size: 'tiny', quaternary: true, type: 'error', onClick: () => remove(row) },
            { icon: () => h(NIcon, null, { default: () => h(TrashOutline) }) }),
        ],
      })
    },
  },
]
</script>

<template>
  <div class="knowledge-page">
    <div class="page-header">
      <h1>知识库管理</h1>
      <div class="header-actions">
        <n-button quaternary @click="showReindexAllModal = true">
          <template #icon><n-icon :component="RefreshOutline" /></template>
          全量重建索引
        </n-button>
      </div>
    </div>

    <!-- Summary Cards -->
    <div class="summary-row">
      <n-card size="small"><div class="stat-label">文档总数</div><div class="stat-value">{{ indexState.total_documents }}</div></n-card>
      <n-card size="small"><div class="stat-label">总分块数</div><div class="stat-value">{{ indexState.total_chunks }}</div></n-card>
      <n-card size="small"><div class="stat-label">已就绪</div><div class="stat-value">{{ indexState.ready_documents }}</div></n-card>
      <n-card size="small"><div class="stat-label">最后索引</div><div class="stat-value stat-time">{{ formatTime(indexState.last_indexed_at) }}</div></n-card>
    </div>

    <!-- Upload + Table -->
    <div class="content-row">
      <n-card size="small" title="上传文档" class="upload-card">
        <n-upload
          multiple
          directory-dnd
          accept=".pdf,.md"
          :custom-request="handleUpload"
          :show-file-list="false"
        >
          <n-button block>
            <template #icon><n-icon :component="CloudUploadOutline" /></template>
            点击或拖拽上传 (.pdf / .md)
          </n-button>
        </n-upload>
      </n-card>

      <n-card size="small" title="文档列表" class="table-card">
        <n-data-table
          :columns="columns"
          :data="documents"
          :loading="loading"
          :pagination="{ pageSize: 20 }"
          flex-height
          striped
          size="small"
        />
      </n-card>
    </div>

    <!-- Progress Section -->
    <div v-if="Object.keys(progressMap).length" class="progress-section">
      <n-card size="small" title="索引进度">
        <div v-for="(prog, docId) in progressMap" :key="docId" class="progress-item">
          <div class="progress-filename">
            {{ documents.find(d => d.id === docId)?.filename || docId }}
          </div>
          <div class="progress-bar-row">
            <n-tag :type="statusTag(prog.phase).type" size="small" :bordered="false">
              {{ statusTag(prog.phase).label }}
            </n-tag>
            <n-progress
              v-if="prog.total > 0"
              type="line"
              :percentage="Math.round((prog.indexed / prog.total) * 100)"
              :height="20"
              :border-radius="4"
              :fill-border-radius="4"
              style="flex:1"
            />
          </div>
        </div>
      </n-card>
    </div>

    <!-- Reindex All Modal -->
    <n-modal
      v-model:show="showReindexAllModal"
      preset="dialog"
      title="全量重建索引"
      content="将重新解析并索引所有已上传文档，可能需要几分钟。确认继续？"
      positive-text="确认"
      negative-text="取消"
      @positive-click="handleReindexAll"
    />
  </div>
</template>

<style scoped>
.knowledge-page {
  padding: 24px;
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.page-header h1 {
  font-size: 22px;
  font-weight: 600;
  color: var(--text-0);
  margin: 0;
}
.summary-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.stat-label {
  font-size: 12px;
  color: var(--text-3);
  margin-bottom: 4px;
}
.stat-value {
  font-size: 24px;
  font-weight: 600;
  color: var(--text-0);
}
.stat-time {
  font-size: 13px;
}
.content-row {
  display: grid;
  grid-template-columns: 220px 1fr;
  gap: 16px;
  align-items: start;
}
.upload-card {
  position: sticky;
  top: 24px;
}
.progress-item {
  margin-bottom: 12px;
}
.progress-filename {
  font-size: 13px;
  color: var(--text-1);
  margin-bottom: 6px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.progress-bar-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
</style>
