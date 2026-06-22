<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted, h } from 'vue'
import { useRouter } from 'vue-router'
import {
  NDataTable, NUpload, NButton, NProgress,
  NIcon, NModal, NAlert, useMessage,
  type DataTableColumn, type UploadFileInfo,
} from 'naive-ui'
import {
  TrashOutline, RefreshOutline, CloudUploadOutline,
  DocumentTextOutline, AlertCircleOutline, CheckmarkCircleOutline,
  ArrowBackOutline,
} from '@vicons/ionicons5'
import {
  fetchDocuments, uploadDocument, deleteDocument, reindexDocument,
  reindexAll, cancelIndexing, fetchIndexState, getProgressSSEUrl,
  type KnowledgeDocument, type IndexStateResponse,
} from '@/api/knowledge'

defineOptions({ name: 'KnowledgeView' })

const router = useRouter()
const msg = useMessage()
const documents = ref<KnowledgeDocument[]>([])
const indexState = ref<IndexStateResponse>({ total_documents: 0, total_chunks: 0, ready_documents: 0, last_indexed_at: null })
const loading = ref(false)
const showReindexAllModal = ref(false)
const reindexPassword = ref('')
const progressMap = ref<Record<string, { phase: string; indexed: number; total: number; error?: string }>>({})
const eventSources: Record<string, EventSource> = {}
const activeCategory = ref<'all' | 'project' | 'technical'>('all')
const errorDetailTarget = ref<KnowledgeDocument | null>(null)

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

function formatTimeParts(iso: string | null) {
  if (!iso) return null
  const d = new Date(iso)
  const month = `${d.getMonth() + 1}`.padStart(2, '0')
  const day = `${d.getDate()}`.padStart(2, '0')
  return {
    date: `${d.getFullYear()}-${month}-${day}`,
    time: d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }),
  }
}

function documentCategory(doc: KnowledgeDocument): 'project' | 'technical' {
  const name = doc.filename.toLowerCase()
  if (
    name.includes('manual') ||
    name.includes('api') ||
    name.includes('sql') ||
    name.includes('gbase') ||
    name.includes('tech') ||
    name.includes('技术') ||
    name.includes('手册') ||
    doc.file_type === 'pdf'
  ) {
    return 'technical'
  }
  return 'project'
}

const categoryItems = computed(() => {
  const projectCount = documents.value.filter(d => documentCategory(d) === 'project').length
  const technicalCount = documents.value.filter(d => documentCategory(d) === 'technical').length
  return [
    { key: 'all' as const, label: '全部文档', count: documents.value.length },
    { key: 'project' as const, label: '项目文档', count: projectCount },
    { key: 'technical' as const, label: '技术文档', count: technicalCount },
  ]
})

const visibleDocuments = computed(() => {
  if (activeCategory.value === 'all') return documents.value
  return documents.value.filter(d => documentCategory(d) === activeCategory.value)
})

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

const deleteTarget = ref<KnowledgeDocument | null>(null)

function confirmRemove(doc: KnowledgeDocument) {
  deleteTarget.value = doc
}

async function doRemove() {
  if (!deleteTarget.value) return
  const doc = deleteTarget.value
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
  deleteTarget.value = null
}

async function remove(doc: KnowledgeDocument) {
  confirmRemove(doc)
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
  if (!reindexPassword.value.trim()) {
    msg.warning('请输入管理密码')
    return
  }
  try {
    await reindexAll(reindexPassword.value)
    showReindexAllModal.value = false
    reindexPassword.value = ''
    msg.success('全量重建已触发')
    load()
  } catch (e: any) {
    msg.error(e.message || '重建失败，请检查密码是否正确')
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
    title: '文件', key: 'filename', width: 360,
    render(row) {
      return h('span', { class: 'doc-file-name', title: row.filename }, row.filename)
    },
  },
  {
    title: '类型', key: 'file_type', width: 74,
    render(row) {
      const label = row.file_type === 'pdf' ? 'PDF' : row.file_type.toUpperCase()
      return h('span', { class: ['doc-type-badge', `is-${row.file_type}`] }, label)
    },
  },
  { title: '大小', key: 'file_size', width: 86, render(row: KnowledgeDocument) { return h('span', { class: 'mono-cell' }, formatSize(row.file_size)) } },
  {
    title: '状态', key: 'status', width: 96,
    render(row) {
      const t = statusTagConfig(row.status)
      return h('span', { class: ['doc-status-pill', `status-${row.status}`] }, [
        h('span', { class: 'doc-status-dot' }),
        h('span', t.label),
      ])
    },
  },
  { title: '分块数', key: 'chunk_count', width: 76, render(row: KnowledgeDocument) { return h('span', { class: 'mono-cell' }, row.chunk_count || '-') } },
  {
    title: '索引时间', key: 'indexed_at', width: 112,
    render(row: KnowledgeDocument) {
      const parts = formatTimeParts(row.indexed_at)
      if (!parts) return h('span', { class: 'muted-cell' }, '-')
      return h('div', { class: 'time-cell' }, [
        h('span', { class: 'time-date' }, parts.date),
        h('span', { class: 'time-clock' }, parts.time),
      ])
    },
  },
  {
    title: '错误信息', key: 'error_message', width: 78,
    render(row: KnowledgeDocument) {
      if (!row.error_message) return h('span', { class: 'muted-cell' }, '-')
      return h('button', {
        class: 'error-open-btn',
        type: 'button',
        title: '查看完整错误',
        'aria-label': '查看错误详情',
        onClick: (event: MouseEvent) => {
          event.stopPropagation()
          errorDetailTarget.value = row
        },
      }, '详情')
    },
  },
  {
    title: '操作', key: 'actions', width: 92, align: 'right',
    render(row) {
      return h('div', { class: 'doc-actions' }, [
        h('button', {
          class: 'doc-action-btn reindex',
          type: 'button',
          title: '重新索引',
          'aria-label': '重新索引',
          onClick: (event: MouseEvent) => {
            event.stopPropagation()
            reindex(row)
          },
        }, [h(NIcon, { size: 15 }, { default: () => h(RefreshOutline) })]),
        h('button', {
          class: 'doc-action-btn danger',
          type: 'button',
          title: '删除',
          'aria-label': '删除',
          onClick: (event: MouseEvent) => {
            event.stopPropagation()
            remove(row)
          },
        }, [h(NIcon, { size: 15 }, { default: () => h(TrashOutline) })]),
      ])
    },
  },
]
</script>

<template>
  <div class="page-shell knowledge-page">
    <!-- Header -->
    <header class="kb-header">
      <button class="back-btn" @click="router.push('/')">
        <n-icon :component="ArrowBackOutline" size="16" />
        <span>返回</span>
      </button>
      <span class="header-title">知识库管理</span>
    </header>

    <div class="kb-body">
    <div class="page-header">
      <div>
        <p class="page-subtitle">管理文档上传、索引和向量化，提升 RAG 检索质量</p>
      </div>
      <n-button quaternary @click="showReindexAllModal = true">
        <template #icon><n-icon :component="RefreshOutline" /></template>
        全量重建索引
      </n-button>
    </div>

    <div class="kb-layout">
      <aside class="category-nav">
        <button
          v-for="item in categoryItems"
          :key="item.key"
          :class="['category-item', { active: activeCategory === item.key }]"
          @click="activeCategory = item.key"
        >
          <span>{{ item.label }}</span>
          <span class="category-count">{{ item.count }}</span>
        </button>
      </aside>

      <main class="kb-content">
        <!-- Summary Cards -->
        <div class="summary-row">
          <div class="stat-card">
            <div class="stat-icon tone-blue">
              <n-icon :component="DocumentTextOutline" size="20" />
            </div>
            <div class="stat-body">
              <div class="stat-label">文档总数</div>
              <div class="stat-value">{{ indexState.total_documents }}</div>
            </div>
          </div>
          <div class="stat-card">
            <div class="stat-icon tone-violet">
              <n-icon :component="CloudUploadOutline" size="20" />
            </div>
            <div class="stat-body">
              <div class="stat-label">总分块数</div>
              <div class="stat-value">{{ indexState.total_chunks }}</div>
            </div>
          </div>
          <div class="stat-card">
            <div class="stat-icon tone-green">
              <n-icon :component="CheckmarkCircleOutline" size="20" />
            </div>
            <div class="stat-body">
              <div class="stat-label">已就绪</div>
              <div class="stat-value">{{ indexState.ready_documents }}</div>
            </div>
          </div>
          <div class="stat-card">
            <div class="stat-icon tone-amber">
              <n-icon :component="RefreshOutline" size="20" />
            </div>
            <div class="stat-body">
              <div class="stat-label">最后索引时间</div>
              <div class="stat-value stat-time">{{ formatTime(indexState.last_indexed_at) }}</div>
            </div>
          </div>
        </div>

        <!-- Drag Upload Zone -->
        <div class="upload-zone">
          <div class="upload-icon-wrap">
            <n-icon :component="CloudUploadOutline" size="22" />
          </div>
          <div class="upload-title">点击或拖拽文件到此处上传</div>
          <div class="upload-hint">支持 PDF, Markdown, TXT, DOCX（最大 50MB）</div>
          <n-upload
            multiple
            directory-dnd
            accept=".pdf,.md,.txt,.docx"
            :custom-request="handleUpload"
            :show-file-list="false"
            class="upload-control"
          >
            <button class="upload-select-btn" type="button">选择文件</button>
          </n-upload>
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
            :data="visibleDocuments"
            :loading="loading"
            table-layout="fixed"
            :pagination="{
              pageSize: 20,
              showSizePicker: false,
              showQuickJumper: false,
              prefix: () => `共 ${visibleDocuments.length} 条`,
            }"
            size="small"
            :bordered="false"
            :empty-text="'暂无文档，上传 PDF 或 Markdown 文件开始构建知识库'"
          />
        </div>
      </main>
    </div>

    <n-modal
      v-model:show="showReindexAllModal"
      preset="dialog"
      title="重建向量索引"
      positive-text="确认重建"
      negative-text="取消"
      :show-icon="false"
      @positive-click="handleReindexAll"
    >
      <p style="margin-bottom:12px;font-size:13px;color:#888;">此操作将重新解析所有文档并重建向量索引，可能需要几分钟。</p>
      <n-input
        v-model:value="reindexPassword"
        type="password"
        placeholder="输入管理密码"
        show-password-on="click"
        @keydown.enter="handleReindexAll"
      />
    </n-modal>

    <!-- Error Detail Modal -->
    <n-modal
      :show="errorDetailTarget !== null"
      :on-update:show="(v: boolean) => { if (!v) errorDetailTarget = null }"
      transform-origin="center"
    >
      <div class="error-detail-modal">
        <div class="error-detail-head">
          <div>
            <div class="error-detail-title">索引错误详情</div>
            <div class="error-detail-file">{{ errorDetailTarget?.filename }}</div>
          </div>
          <button class="error-detail-close" @click="errorDetailTarget = null">关闭</button>
        </div>
        <pre class="error-detail-content">{{ errorDetailTarget?.error_message }}</pre>
      </div>
    </n-modal>

    <!-- Delete Document Modal -->
    <n-modal
      :show="deleteTarget !== null"
      :on-update:show="(v: boolean) => { if (!v) deleteTarget = null }"
      transform-origin="center"
    >
      <div class="delete-modal">
        <div class="delete-modal-body">
          <div class="delete-modal-icon">
            <n-icon :component="AlertCircleOutline" size="24" />
          </div>
          <div class="delete-modal-title">确认删除文档？</div>
          <div class="delete-modal-desc">将永久删除「{{ deleteTarget?.filename || '' }}」及其向量索引，此操作无法恢复。</div>
        </div>
        <div class="delete-modal-actions">
          <button class="delete-modal-btn cancel" @click="deleteTarget = null">取消</button>
          <button class="delete-modal-btn confirm" @click="doRemove">确认删除</button>
        </div>
      </div>
    </n-modal>
    </div><!-- kb-body -->
  </div>
</template>

<style scoped>
.knowledge-page {
  height: 100vh; display: flex; flex-direction: column; overflow: hidden;
  background: var(--bg-page);
}

.kb-header {
  display: flex; align-items: center; gap: 12px;
  padding: 0 24px; height: 48px;
  border-bottom: 1px solid var(--border-card); background: var(--bg-header); flex-shrink: 0;
}
.back-btn {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 13px; color: var(--text-3);
  background: var(--bg-panel); border: 1px solid var(--seam-1);
  border-radius: var(--radius-md); padding: 5px 10px;
  cursor: pointer; transition: all var(--duration-fast);
}
.back-btn:hover { color: var(--text-0); border-color: var(--seam-2); }
.header-title { font-size: 15px; font-weight: 600; color: var(--text-brand); }

.kb-body {
  flex: 1; overflow-y: auto;
  padding: 24px 40px 80px;
  max-width: 1320px; margin: 0 auto; width: 100%;
  display: flex; flex-direction: column; gap: 18px;
}

/* ── Header ── */
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}
.page-subtitle {
  font-size: 13px;
  color: var(--text-3);
  margin: 0;
}

.kb-layout {
  display: grid;
  grid-template-columns: 160px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.category-nav {
  position: sticky;
  top: 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 6px;
  background: var(--bg-header);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-lg);
}

.category-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  padding: 9px 10px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-2);
  font-size: 13px;
  font-weight: 500;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: all var(--duration-fast);
}
.category-item:hover {
  background: rgba(37, 99, 235, 0.04);
  color: var(--text-0);
}
.category-item.active {
  background: rgba(37, 99, 235, 0.08);
  color: #1d4ed8;
  border-color: rgba(37, 99, 235, 0.16);
  font-weight: 600;
}
.category-count {
  min-width: 24px;
  text-align: center;
  padding: 1px 6px;
  border-radius: var(--radius-full);
  background: var(--bg-surface);
  color: var(--text-3);
  border: 1px solid var(--seam-1);
  font-size: 11px;
  font-family: var(--font-mono);
}
.category-item.active .category-count {
  background: rgba(37, 99, 235, 0.1);
  border-color: rgba(37, 99, 235, 0.18);
  color: #1d4ed8;
}

.kb-content {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 20px;
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
  background: var(--bg-header);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-lg);
  padding: 16px 18px;
  box-shadow: var(--shadow-sm);
}
.stat-icon {
  width: 42px;
  height: 42px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  color: var(--text-2);
}
.stat-icon.tone-blue {
  background: rgba(37, 99, 235, 0.08);
  border-color: rgba(37, 99, 235, 0.14);
  color: #2563eb;
}
.stat-icon.tone-violet {
  background: rgba(124, 58, 237, 0.08);
  border-color: rgba(124, 58, 237, 0.14);
  color: #7c3aed;
}
.stat-icon.tone-green {
  background: rgba(22, 163, 74, 0.08);
  border-color: rgba(22, 163, 74, 0.16);
  color: var(--success);
}
.stat-icon.tone-amber {
  background: rgba(217, 119, 6, 0.08);
  border-color: rgba(217, 119, 6, 0.16);
  color: #d97706;
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

/* ── Upload Zone ── */
.upload-zone {
  border: 2px dashed #d5ddea;
  border-radius: 14px;
  padding: 32px;
  text-align: center;
  background: var(--bg-header);
  transition: all 0.2s;
  cursor: pointer;
}
.upload-zone:hover {
  border-color: rgba(37, 99, 235, 0.42);
  background: rgba(37, 99, 235, 0.02);
}
.upload-icon-wrap {
  width: 48px; height: 48px;
  background: var(--bg-panel); border: 1px solid var(--seam-1);
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  margin: 0 auto 12px; color: var(--text-3);
}
.upload-title {
  font-size: 14px; font-weight: 600; color: var(--text-brand); margin-bottom: 4px;
}
.upload-hint {
  font-size: 11px; color: var(--text-4);
}
.upload-control {
  margin-top: 12px;
}
.upload-select-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 7px 14px;
  border-radius: var(--radius-md);
  border: 1px solid var(--text-0);
  background: var(--text-0);
  color: var(--bg-void);
  font-size: 12px;
  font-weight: 600;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: all var(--duration-fast);
}
.upload-select-btn:hover {
  background: var(--text-1);
  border-color: var(--text-1);
}

/* ── Toolbar (removed, absorbed by upload zone) ── */
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
  color: var(--text-0);
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
  background: var(--bg-header);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}
.table-wrapper :deep(.n-data-table) {
  --n-th-color: #f8fafc !important;
  --n-td-color: var(--bg-header) !important;
  --n-td-color-striped: var(--bg-header) !important;
  --n-td-color-hover: rgba(37, 99, 235, 0.025) !important;
  --n-border-color: var(--seam-1) !important;
  --n-th-text-color: var(--text-2) !important;
  --n-td-text-color: var(--text-1) !important;
  font-size: 13px;
  width: 100%;
  table-layout: fixed;
}
.table-wrapper :deep(.n-data-table-table) {
  width: 100% !important;
  min-width: 0 !important;
  table-layout: fixed !important;
}
.table-wrapper :deep(.n-data-table-th) {
  font-weight: 600;
  white-space: nowrap;
  height: 40px;
  padding: 0 12px;
  background: #f8fafc !important;
  font-size: 12px;
}
.table-wrapper :deep(.n-data-table-td) {
  vertical-align: middle;
  height: 56px;
  padding: 10px 12px;
  border-bottom-color: var(--seam-1) !important;
}
.table-wrapper :deep(.n-data-table-tr:last-child .n-data-table-td) {
  border-bottom: none !important;
}
.table-wrapper :deep(.n-data-table-tr:hover .n-data-table-td) {
  background: rgba(37, 99, 235, 0.025) !important;
}
.table-wrapper :deep(.n-data-table-base-table-body) {
  overflow-x: hidden !important;
}
.table-wrapper :deep(.n-scrollbar-container),
.table-wrapper :deep(.n-scrollbar-content) {
  max-width: 100% !important;
}
.table-wrapper :deep(.n-scrollbar-rail--horizontal) {
  display: none !important;
}
.table-wrapper :deep(.doc-file-name) {
  display: block;
  max-width: 100%;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #1f2937;
  font-size: 13px;
  font-weight: 500;
  line-height: 1.45;
}
.table-wrapper :deep(.doc-type-badge) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 42px;
  height: 24px;
  padding: 0 8px;
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-sm);
  background: var(--bg-panel);
  color: var(--text-2);
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
}
.table-wrapper :deep(.doc-type-badge.is-pdf) {
  background: rgba(37, 99, 235, 0.07);
  border-color: rgba(37, 99, 235, 0.14);
  color: #2563eb;
}
.table-wrapper :deep(.doc-status-pill) {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 24px;
  padding: 0 9px;
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-full);
  background: var(--bg-surface);
  color: var(--text-2);
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
}
.table-wrapper :deep(.doc-status-dot) {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-4);
  flex-shrink: 0;
}
.table-wrapper :deep(.doc-status-pill.status-ready .doc-status-dot) {
  background: var(--success);
}
.table-wrapper :deep(.doc-status-pill.status-ready) {
  border-color: rgba(22, 163, 74, 0.18);
  background: rgba(22, 163, 74, 0.07);
  color: #15803d;
}
.table-wrapper :deep(.doc-status-pill.status-error) {
  border-color: rgba(220, 38, 38, 0.18);
  background: rgba(220, 38, 38, 0.04);
  color: var(--error);
}
.table-wrapper :deep(.doc-status-pill.status-error .doc-status-dot) {
  background: var(--error);
}
.table-wrapper :deep(.doc-status-pill.status-parsing .doc-status-dot),
.table-wrapper :deep(.doc-status-pill.status-chunking .doc-status-dot),
.table-wrapper :deep(.doc-status-pill.status-indexing .doc-status-dot) {
  background: #2563eb;
}
.table-wrapper :deep(.doc-status-pill.status-parsing),
.table-wrapper :deep(.doc-status-pill.status-chunking),
.table-wrapper :deep(.doc-status-pill.status-indexing) {
  border-color: rgba(37, 99, 235, 0.16);
  background: rgba(37, 99, 235, 0.06);
  color: #1d4ed8;
}
.table-wrapper :deep(.doc-status-pill.status-pending) {
  border-color: rgba(217, 119, 6, 0.16);
  background: rgba(217, 119, 6, 0.06);
  color: #b45309;
}
.table-wrapper :deep(.doc-status-pill.status-pending .doc-status-dot) {
  background: #d97706;
}
.table-wrapper :deep(.mono-cell) {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-2);
  white-space: nowrap;
}
.table-wrapper :deep(.muted-cell) {
  color: var(--text-4);
}
.table-wrapper :deep(.time-cell) {
  display: grid;
  gap: 2px;
  justify-items: start;
  font-family: var(--font-mono);
  line-height: 1.15;
  white-space: nowrap;
}
.table-wrapper :deep(.time-date) {
  color: var(--text-1);
  font-size: 11px;
  font-weight: 500;
}
.table-wrapper :deep(.time-clock) {
  color: var(--text-4);
  font-size: 10px;
}
.table-wrapper :deep(.error-open-btn) {
  appearance: none;
  -webkit-appearance: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 26px;
  padding: 0 10px;
  border: 1px solid rgba(220, 38, 38, 0.16);
  border-radius: var(--radius-sm);
  background: rgba(220, 38, 38, 0.04);
  color: #b91c1c;
  font-size: 12px;
  font-weight: 600;
  font-family: var(--font-sans);
  line-height: 1;
  cursor: pointer;
  transition: all var(--duration-fast);
}
.table-wrapper :deep(.error-open-btn:hover) {
  border-color: rgba(220, 38, 38, 0.26);
  background: rgba(220, 38, 38, 0.08);
  color: var(--error);
}
.table-wrapper :deep(.doc-actions) {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  transition: opacity var(--duration-fast);
}
.table-wrapper :deep(.doc-action-btn) {
  appearance: none;
  -webkit-appearance: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  padding: 0;
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-sm);
  background: var(--bg-header);
  color: var(--text-2);
  cursor: pointer;
  transition: all var(--duration-fast);
  box-shadow: 0 1px 1px rgba(15, 23, 42, 0.02);
}
.table-wrapper :deep(.doc-action-btn.reindex:hover) {
  background: rgba(37, 99, 235, 0.07);
  border-color: rgba(37, 99, 235, 0.2);
  color: #2563eb;
}
.table-wrapper :deep(.doc-action-btn.danger) {
  color: var(--text-2);
}
.table-wrapper :deep(.doc-action-btn.danger:hover) {
  color: var(--error);
  background: rgba(220, 38, 38, 0.07);
  border-color: rgba(220, 38, 38, 0.16);
}
.table-wrapper :deep(.n-data-table__pagination) {
  justify-content: flex-end;
  padding: 11px 14px 12px;
  border-top: 1px solid var(--seam-1);
  background: #f8fafc;
}
.table-wrapper :deep(.n-pagination) {
  width: 100%;
  gap: 4px;
}
.table-wrapper :deep(.n-pagination-prefix) {
  color: var(--text-3);
  font-size: 12px;
  margin-right: auto;
}
.table-wrapper :deep(.n-pagination-item) {
  min-width: 26px;
  height: 26px;
  border-radius: var(--radius-sm) !important;
  border: 1px solid transparent !important;
  background: transparent !important;
  color: var(--text-2) !important;
  font-size: 12px;
  font-family: var(--font-mono);
  transition: all var(--duration-fast);
}
.table-wrapper :deep(.n-pagination-item:hover) {
  border-color: var(--seam-1) !important;
  background: var(--bg-header) !important;
  color: var(--text-0) !important;
}
.table-wrapper :deep(.n-pagination-item--active) {
  border-color: var(--text-0) !important;
  background: var(--text-0) !important;
  color: var(--bg-void) !important;
  box-shadow: var(--shadow-sm);
}
.table-wrapper :deep(.n-pagination-item--disabled) {
  opacity: 0.45;
  cursor: not-allowed;
}

/* ── Error Detail Modal ── */
.error-detail-modal {
  width: min(720px, calc(100vw - 40px));
  max-height: min(640px, calc(100vh - 80px));
  display: flex;
  flex-direction: column;
  background: var(--bg-header);
  border: 1px solid var(--seam-1);
  border-radius: 18px;
  overflow: hidden;
  box-shadow: var(--shadow-lg);
  animation: modalIn 0.25s var(--ease-spring) both;
}
.error-detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 20px;
  border-bottom: 1px solid var(--seam-1);
  background: var(--bg-page);
}
.error-detail-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-0);
  margin-bottom: 4px;
}
.error-detail-file {
  max-width: 540px;
  color: var(--text-3);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.error-detail-close {
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-sm);
  background: var(--bg-header);
  color: var(--text-2);
  font-size: 12px;
  padding: 6px 12px;
  cursor: pointer;
  transition: all var(--duration-fast);
}
.error-detail-close:hover {
  border-color: var(--seam-2);
  color: var(--text-0);
}
.error-detail-content {
  margin: 0;
  padding: 18px 20px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--text-1);
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.7;
  background: var(--bg-header);
}

/* ── Delete Modal ── */
.delete-modal {
  background: var(--bg-header);
  border-radius: 18px;
  overflow: hidden;
  width: 380px;
  box-shadow: 0 20px 60px rgba(0,0,0,0.15);
  animation: modalIn 0.25s cubic-bezier(0.34,1.56,0.64,1) both;
}
.delete-modal-body {
  padding: 32px 24px 20px;
  text-align: center;
}
.delete-modal-icon {
  width: 52px; height: 52px;
  background: rgba(220, 38, 38, 0.08); border: 1px solid rgba(220, 38, 38, 0.18);
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  margin: 0 auto 16px;
  color: var(--error);
}
.delete-modal-title {
  font-size: 17px; font-weight: 700;
  color: var(--text-brand); letter-spacing: -0.01em;
  margin-bottom: 8px;
}
.delete-modal-desc {
  font-size: 13px; color: var(--text-3); line-height: 1.5;
  max-width: 280px; margin: 0 auto;
}
.delete-modal-actions {
  display: flex; border-top: 1px solid var(--seam-1);
}
.delete-modal-btn {
  flex: 1; padding: 14px;
  font-size: 14px; font-weight: 500;
  background: none; border: none; cursor: pointer;
  transition: background 0.15s;
}
.delete-modal-btn.cancel {
  color: var(--text-3); border-right: 1px solid var(--seam-1);
}
.delete-modal-btn.cancel:hover { background: var(--bg-hover); }
.delete-modal-btn.confirm {
  color: var(--error); font-weight: 600;
}
.delete-modal-btn.confirm:hover { background: rgba(220, 38, 38, 0.08); }

@media (max-width: 1280px) {
  .kb-layout {
    grid-template-columns: 1fr;
  }
  .category-nav {
    position: static;
    display: grid;
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 1180px) {
  .kb-body {
    padding-inline: 24px;
  }
}

@media (max-width: 960px) {
  .summary-row {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 760px) {
  .category-item {
    flex-direction: column;
    align-items: flex-start;
  }
}

@media (max-width: 560px) {
  .summary-row,
  .category-nav {
    grid-template-columns: 1fr;
  }
  .upload-zone {
    padding: 24px 16px;
  }
}
</style>
