<script setup lang="ts">
import { ref, onMounted, onUnmounted, h } from 'vue'
import {
  NCard, NDataTable, NUpload, NButton, NTag, NProgress,
  NIcon, NSpace, NModal, useMessage,
  type DataTableColumn, type UploadFileInfo,
} from 'naive-ui'
import { TrashOutline, RefreshOutline, CloudUploadOutline, DocumentTextOutline } from '@vicons/ionicons5'
import {
  fetchDocuments, uploadDocument, deleteDocument, reindexDocument,
  reindexAll, fetchIndexState, getProgressSSEUrl,
  type KnowledgeDocument, type IndexStateResponse,
} from '@/api/knowledge'

defineOptions({ name: 'KnowledgeView' })

const msg = useMessage()
const documents = ref<KnowledgeDocument[]>([])
const indexState = ref<IndexStateResponse>({ total_documents: 0, total_chunks: 0, ready_documents: 0, last_indexed_at: null })
const loading = ref(false)
const showReindexAllModal = ref(false)
const progressMap = ref<Record<string, { phase: string; indexed: number; total: number }>>({})
const eventSources: Record<string, EventSource> = {}

function statusTagConfig(status: string) {
  const map: Record<string, { type: 'default' | 'info' | 'success' | 'warning' | 'error'; label: string }> = {
    pending:  { type: 'default', label: '等待中' },
    parsing:  { type: 'info',    label: '解析中' },
    chunking: { type: 'info',    label: '切片中' },
    indexing: { type: 'info',    label: '索引中' },
    ready:    { type: 'success', label: '就绪' },
    error:    { type: 'error',   label: '失败' },
  }
  return map[status] || { type: 'default' as const, label: status }
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatTime(iso: string | null) {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('zh-CN')
}

function connectProgress(docId: string) {
  if (eventSources[docId]) return
  const es = new EventSource(getProgressSSEUrl(docId))
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
        es.close(); delete eventSources[docId]
        load()
      } else if (event === 'error') {
        delete progressMap.value[docId]
        es.close(); delete eventSources[docId]
        load()
      }
    } catch { /* ignore */ }
  }
  es.onerror = () => { es.close(); delete eventSources[docId] }
  eventSources[docId] = es
}

async function load() {
  loading.value = true
  try {
    const [docsRes, stateRes] = await Promise.all([fetchDocuments({}), fetchIndexState()])
    documents.value = docsRes.documents
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
    if (eventSources[doc.id]) { eventSources[doc.id].close(); delete eventSources[doc.id] }
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
onUnmounted(() => { Object.values(eventSources).forEach(es => es.close()) })

const columns: DataTableColumn<KnowledgeDocument>[] = [
  {
    title: '文件名', key: 'filename', ellipsis: { tooltip: true }, width: 280,
    render(row) {
      return h('div', { style: { display: 'flex', alignItems: 'center', gap: '8px' } }, [
        h(NIcon, { size: 16, color: 'var(--text-3)' }, { default: () => h(DocumentTextOutline) }),
        h('span', row.filename),
      ])
    },
  },
  {
    title: '类型', key: 'file_type', width: 70,
    render(row) {
      const t = row.file_type === 'pdf' ? { type: 'error' as const, label: 'PDF' } : { type: 'info' as const, label: 'MD' }
      return h(NTag, { type: t.type, size: 'small', bordered: false }, { default: () => t.label })
    },
  },
  { title: '大小', key: 'file_size', width: 90, render(row: KnowledgeDocument) { return formatSize(row.file_size) } },
  {
    title: '状态', key: 'status', width: 90,
    render(row) {
      const t = statusTagConfig(row.status)
      return h(NTag, { type: t.type, size: 'small', bordered: false }, { default: () => t.label })
    },
  },
  { title: '分块数', key: 'chunk_count', width: 70, render(row: KnowledgeDocument) { return row.chunk_count || '-' } },
  { title: '索引时间', key: 'indexed_at', width: 160, render(row: KnowledgeDocument) { return formatTime(row.indexed_at) } },
  {
    title: '操作', key: 'actions', width: 100,
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
    <!-- Header -->
    <div class="page-header">
      <h1>知识库管理</h1>
      <n-button quaternary @click="showReindexAllModal = true">
        <template #icon><n-icon :component="RefreshOutline" /></template>
        全量重建索引
      </n-button>
    </div>

    <!-- Summary Cards -->
    <div class="summary-row">
      <div class="stat-card">
        <div class="stat-icon docs-icon"><n-icon :component="DocumentTextOutline" size="20" /></div>
        <div class="stat-body">
          <div class="stat-label">文档总数</div>
          <div class="stat-value">{{ indexState.total_documents }}</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon chunks-icon"><n-icon :component="CloudUploadOutline" size="20" /></div>
        <div class="stat-body">
          <div class="stat-label">总分块数</div>
          <div class="stat-value">{{ indexState.total_chunks }}</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon ready-icon" style="background: rgba(22,163,74,0.1); color: var(--success)">✓</div>
        <div class="stat-body">
          <div class="stat-label">已就绪</div>
          <div class="stat-value">{{ indexState.ready_documents }}</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-body" style="flex:1">
          <div class="stat-label">最后索引时间</div>
          <div class="stat-value stat-time">{{ formatTime(indexState.last_indexed_at) }}</div>
        </div>
      </div>
    </div>

    <!-- Upload Area -->
    <div class="upload-row">
      <n-upload
        multiple
        directory-dnd
        accept=".pdf,.md"
        :custom-request="handleUpload"
        :show-file-list="false"
      >
        <n-button size="small" :loading="false">
          <template #icon><n-icon :component="CloudUploadOutline" /></template>
          上传文档 (.pdf / .md)
        </n-button>
      </n-upload>
      <span class="upload-hint">支持 PDF 和 Markdown 文件，上传后自动索引</span>
    </div>

    <!-- Indexing Progress (shown above table when active) -->
    <div v-if="Object.keys(progressMap).length" class="progress-row">
      <div v-for="(prog, docId) in progressMap" :key="docId" class="progress-item">
        <div class="progress-header">
          <span class="progress-filename">
            {{ documents.find(d => d.id === docId)?.filename || docId }}
          </span>
          <n-tag :type="statusTagConfig(prog.phase).type" size="tiny" :bordered="false">
            {{ statusTagConfig(prog.phase).label }}
          </n-tag>
        </div>
        <n-progress
          v-if="prog.total > 0"
          type="line"
          :percentage="Math.round((prog.indexed / prog.total) * 100)"
          :height="6"
          :border-radius="3"
          :fill-border-radius="3"
          :indicator-placement="'inside'"
          processing
        />
        <n-progress
          v-else
          type="line"
          :percentage="0"
          :height="6"
          :border-radius="3"
          :fill-border-radius="3"
          :indicator-placement="'inside'"
          processing
        />
      </div>
    </div>

    <!-- Document Table -->
    <div class="table-wrapper">
      <n-data-table
        :columns="columns"
        :data="documents"
        :loading="loading"
        :pagination="{ pageSize: 20 }"
        striped
        size="small"
        :bordered="false"
      />
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
  padding: 24px 32px;
  max-width: 1100px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 20px;
  height: 100%;
  overflow-y: auto;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.page-header h1 {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-0);
  margin: 0;
}

/* ── Summary Cards ── */
.summary-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.stat-card {
  display: flex;
  align-items: center;
  gap: 14px;
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-lg);
  padding: 16px 18px;
}
.stat-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.docs-icon {
  background: rgba(59, 130, 246, 0.1);
  color: #3b82f6;
}
.chunks-icon {
  background: rgba(139, 92, 246, 0.1);
  color: #8b5cf6;
}
.stat-body {
  min-width: 0;
}
.stat-label {
  font-size: 12px;
  color: var(--text-3);
  margin-bottom: 2px;
}
.stat-value {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-0);
  line-height: 1.2;
}
.stat-time {
  font-size: 13px;
  font-weight: 500;
}

/* ── Upload Row ── */
.upload-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.upload-hint {
  font-size: 12px;
  color: var(--text-4);
}

/* ── Progress Row ── */
.progress-row {
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-lg);
  padding: 14px 18px;
}
.progress-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.progress-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.progress-filename {
  font-size: 13px;
  color: var(--text-1);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── Table ── */
.table-wrapper {
  flex: 1;
  min-height: 0;
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-lg);
  overflow: hidden;
}
</style>
