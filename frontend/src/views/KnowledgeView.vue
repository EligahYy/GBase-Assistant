<script setup lang="ts">
import { ref, onMounted, onUnmounted, h } from 'vue'
import {
  NDataTable, NUpload, NButton, NTag, NProgress,
  NIcon, NSpace, NModal, NAlert, useMessage,
  type DataTableColumn, type UploadFileInfo,
} from 'naive-ui'
import {
  TrashOutline, RefreshOutline, CloudUploadOutline,
  DocumentTextOutline, AlertCircleOutline, CheckmarkCircleOutline,
} from '@vicons/ionicons5'
import {
  fetchDocuments, uploadDocument, deleteDocument, reindexDocument,
  reindexAll, cancelIndexing, fetchIndexState, getProgressSSEUrl,
  type KnowledgeDocument, type IndexStateResponse,
} from '@/api/knowledge'

defineOptions({ name: 'KnowledgeView' })

const msg = useMessage()
const documents = ref<KnowledgeDocument[]>([])
const indexState = ref<IndexStateResponse>({ total_documents: 0, total_chunks: 0, ready_documents: 0, last_indexed_at: null })
const loading = ref(false)
const showReindexAllModal = ref(false)
const progressMap = ref<Record<string, { phase: string; indexed: number; total: number; error?: string }>>({})
const eventSources: Record<string, EventSource> = {}

// ── Phase metadata ──
const PHASE_INFO: Record<string, { label: string; description: string }> = {
  parsing:  { label: '解析文件',  description: '正在提取文档内容...' },
  chunking: { label: '智能切片',  description: '正在按语义边界切分文档...' },
  indexing: { label: '向量索引',  description: '正在生成 Embedding 并写入向量库...' },
  ready:    { label: '完成',      description: '索引完成' },
  error:    { label: '失败',      description: '索引失败' },
}

function statusTagConfig(status: string) {
  const map: Record<string, { type: 'default' | 'info' | 'success' | 'warning' | 'error'; label: string }> = {
    pending:   { type: 'default', label: '等待中' },
    parsing:   { type: 'info',    label: '解析中' },
    chunking:  { type: 'info',    label: '切片中' },
    indexing:  { type: 'info',    label: '索引中' },
    ready:     { type: 'success', label: '就绪' },
    error:     { type: 'error',   label: '失败' },
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

  // Initialize progress entry
  progressMap.value[docId] = { phase: 'pending', indexed: 0, total: 0 }

  const es = new EventSource(getProgressSSEUrl(docId))
  es.onmessage = (e) => {
    try {
      const { event, data } = JSON.parse(e.data)
      if (event === 'heartbeat') return

      const entry = progressMap.value[docId]
      if (!entry) return

      if (event === 'progress') {
        // Merge: only update fields present in the event, don't reset others
        if (data.phase) entry.phase = data.phase
        if (typeof data.indexed === 'number') entry.indexed = data.indexed
        if (typeof data.total === 'number') entry.total = data.total
      } else if (event === 'complete') {
        // Show completion briefly, then remove
        entry.phase = 'ready'
        entry.indexed = entry.total || (data.chunk_count as number) || 0
        setTimeout(() => {
          delete progressMap.value[docId]
          load()
        }, 2000)
        es.close(); delete eventSources[docId]
      } else if (event === 'error') {
        entry.phase = 'error'
        entry.error = (data.message as string) || '未知错误'
        // Keep error visible until user dismisses
        es.close(); delete eventSources[docId]
        load()
      }
    } catch { /* ignore malformed SSE data */ }
  }
  es.onerror = () => {
    // SSE disconnected — keep current progress state, reconnect on next load()
    es.close(); delete eventSources[docId]
  }
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
    const eventSource = eventSources[doc.id]
    if (eventSource) { eventSource.close(); delete eventSources[doc.id] }
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

async function cancel(docId: string) {
  try {
    await cancelIndexing(docId)
    if (eventSources[docId]) { eventSources[docId].close(); delete eventSources[docId] }
    delete progressMap.value[docId]
    msg.success('已取消索引')
    load()
  } catch (e: any) {
    msg.error(e.message || '取消失败')
  }
}

function dismissError(docId: string) {
  delete progressMap.value[docId]
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
  {
    title: '错误信息', key: 'error_message', width: 200, ellipsis: { tooltip: true },
    render(row: KnowledgeDocument) {
      if (!row.error_message) return '-'
      return h('span', { style: { color: 'var(--error)', fontSize: '12px' } }, row.error_message)
    },
  },
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
      <div>
        <h1>知识库管理</h1>
        <p class="page-subtitle">管理文档上传、索引和向量化，提升 RAG 检索质量</p>
      </div>
      <n-button quaternary @click="showReindexAllModal = true">
        <template #icon><n-icon :component="RefreshOutline" /></template>
        全量重建索引
      </n-button>
    </div>

    <!-- Summary Cards -->
    <div class="summary-row">
      <div class="stat-card">
        <div class="stat-icon" style="background:rgba(59,130,246,.1);color:#3b82f6">
          <n-icon :component="DocumentTextOutline" size="20" />
        </div>
        <div class="stat-body">
          <div class="stat-label">文档总数</div>
          <div class="stat-value">{{ indexState.total_documents }}</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon" style="background:rgba(139,92,246,.1);color:#8b5cf6">
          <n-icon :component="CloudUploadOutline" size="20" />
        </div>
        <div class="stat-body">
          <div class="stat-label">总分块数</div>
          <div class="stat-value">{{ indexState.total_chunks }}</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon" style="background:rgba(22,163,74,.1);color:var(--success)">
          <n-icon :component="CheckmarkCircleOutline" size="20" />
        </div>
        <div class="stat-body">
          <div class="stat-label">已就绪</div>
          <div class="stat-value">{{ indexState.ready_documents }}</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon" style="background:rgba(245,158,11,.1);color:#f59e0b">
          <n-icon :component="RefreshOutline" size="20" />
        </div>
        <div class="stat-body">
          <div class="stat-label">最后索引时间</div>
          <div class="stat-value stat-time">{{ formatTime(indexState.last_indexed_at) }}</div>
        </div>
      </div>
    </div>

    <!-- Upload Toolbar -->
    <div class="toolbar-row">
      <n-upload
        multiple
        directory-dnd
        accept=".pdf,.md"
        :custom-request="handleUpload"
        :show-file-list="false"
      >
        <n-button size="small">
          <template #icon><n-icon :component="CloudUploadOutline" /></template>
          上传文档
        </n-button>
      </n-upload>
      <span class="toolbar-hint">支持 PDF 和 Markdown，上传后自动解析、切片、向量化</span>
    </div>

    <!-- Indexing Progress -->
    <div v-if="Object.keys(progressMap).length" class="progress-section">
      <div
        v-for="(prog, docId) in progressMap"
        :key="docId"
        class="progress-card"
        :class="{ 'is-error': prog.phase === 'error' }"
      >
        <!-- Error state -->
        <template v-if="prog.phase === 'error'">
          <div class="progress-top">
            <div class="progress-title">
              <n-icon :component="AlertCircleOutline" size="18" color="var(--error)" />
              <span class="progress-filename">
                {{ documents.find(d => d.id === docId)?.filename || docId }}
              </span>
              <n-tag type="error" size="tiny" :bordered="false">索引失败</n-tag>
            </div>
            <n-button text size="tiny" @click="dismissError(docId)">关闭</n-button>
          </div>
          <n-alert type="error" :show-icon="false" style="margin-top:8px">
            {{ prog.error || '未知错误，请查看后端日志' }}
          </n-alert>
        </template>

        <!-- Active progress -->
        <template v-else>
          <div class="progress-top">
            <div class="progress-title">
              <span class="progress-filename">
                {{ documents.find(d => d.id === docId)?.filename || docId }}
              </span>
              <n-tag
                :type="prog.phase === 'ready' ? 'success' : 'info'"
                size="tiny"
                :bordered="false"
              >
                {{ PHASE_INFO[prog.phase]?.label || prog.phase }}
              </n-tag>
            </div>
            <div class="progress-actions">
              <span v-if="prog.total > 0" class="progress-pct">
                {{ Math.round((prog.indexed / prog.total) * 100) }}%
              </span>
              <n-button text size="tiny" type="warning" @click="cancel(docId)">
                取消
              </n-button>
            </div>
          </div>
          <div class="progress-desc">
            {{ PHASE_INFO[prog.phase]?.description || '处理中...' }}
          </div>
          <n-progress
            type="line"
            :percentage="prog.total > 0 ? Math.round((prog.indexed / prog.total) * 100) : undefined"
            :height="6"
            :border-radius="3"
            :fill-border-radius="3"
            :show-indicator="false"
            :status="prog.phase === 'ready' ? 'success' : 'default'"
            :color="prog.phase === 'error' ? 'var(--error)' : undefined"
          />
          <div v-if="prog.total > 0" class="progress-count">
            {{ prog.indexed }} / {{ prog.total }} 块
          </div>
        </template>
      </div>
    </div>

    <!-- Document Table -->
    <div class="table-wrapper">
      <n-data-table
        :columns="columns"
        :data="documents"
        :loading="loading"
        :pagination="{
          pageSize: 20,
          showSizePicker: false,
          showQuickJumper: false,
          prefix: () => `共 ${documents.length} 条`,
        }"
        striped
        size="small"
        :bordered="false"
        :empty-text="'暂无文档，上传 PDF 或 Markdown 文件开始构建知识库'"
      />
    </div>

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
  padding: 28px 36px;
  max-width: 1160px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* ── Header ── */
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}
.page-header h1 {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-0);
  margin: 0;
}
.page-subtitle {
  font-size: 13px;
  color: var(--text-3);
  margin: 4px 0 0;
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
  width: 42px;
  height: 42px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.stat-body { min-width: 0; }
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

/* ── Toolbar ── */
.toolbar-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.toolbar-hint {
  font-size: 12px;
  color: var(--text-4);
}

/* ── Progress Section ── */
.progress-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.progress-card {
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-lg);
  padding: 14px 18px;
}
.progress-card.is-error {
  border-color: rgba(220, 38, 38, .2);
  background: rgba(220, 38, 38, .03);
}
.progress-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.progress-title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.progress-filename {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-0);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.progress-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.progress-pct {
  font-size: 18px;
  font-weight: 700;
  color: var(--primary, #3b82f6);
  font-family: var(--font-mono);
}
.progress-desc {
  font-size: 12px;
  color: var(--text-3);
  margin: 6px 0 8px;
}
.progress-count {
  font-size: 11px;
  color: var(--text-4);
  margin-top: 4px;
  text-align: right;
  font-family: var(--font-mono);
}

/* ── Table ── */
.table-wrapper {
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-lg);
  overflow: hidden;
}
.table-wrapper :deep(.n-data-table__pagination) {
  justify-content: center;
}
</style>
