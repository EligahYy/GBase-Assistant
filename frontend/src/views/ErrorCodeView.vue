<script setup lang="ts">
import { ref } from 'vue'
import { NInput, NButton, NTag, NEmpty, NSpin, useMessage } from 'naive-ui'
import { useRouter } from 'vue-router'
import {
  ArrowBackOutline,
  SearchOutline,
  CodeSlashOutline,
  AlertCircleOutline,
} from '@vicons/ionicons5'
import { NIcon } from 'naive-ui'
import { queryErrorCode, type ErrorCodeItem, type ErrorCodeMode } from '@/api/tools'

const router = useRouter()
const naiveMsg = useMessage()

const inputText = ref('')
const isLoading = ref(false)
const mode = ref<ErrorCodeMode | null>(null)
const results = ref<ErrorCodeItem[]>([])
const lastQuery = ref('')

const quickQueries = ['1064', '1146', '2003', 'GBA-2001', '数据倾斜', '连接超时', 'DISTRIBUTED BY']

const modeLabel: Record<ErrorCodeMode, string> = {
  exact: '精确匹配',
  semantic: '语义检索',
  keyword: '关键词匹配',
  empty: '未命中',
}
const modeType: Record<ErrorCodeMode, 'success' | 'info' | 'warning' | 'default'> = {
  exact: 'success',
  semantic: 'info',
  keyword: 'warning',
  empty: 'default',
}

async function handleSearch(query?: string) {
  const text = (query ?? inputText.value).trim()
  if (!text) {
    naiveMsg.warning('请输入错误码或关键词')
    return
  }
  inputText.value = text
  lastQuery.value = text
  isLoading.value = true
  try {
    const resp = await queryErrorCode({ query: text, top_k: 8 })
    mode.value = resp.mode
    results.value = resp.results
    if (resp.results.length === 0) {
      naiveMsg.info('未匹配到相关错误码，可换个关键词试试')
    }
  } catch (e: any) {
    naiveMsg.error(e?.message || '查询失败')
    mode.value = null
    results.value = []
  } finally {
    isLoading.value = false
  }
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSearch()
  }
}

function categoryLabel(cat: string): string {
  const map: Record<string, string> = {
    connection: '连接',
    syntax: '语法',
    table_column: '表/列',
    constraint: '约束',
    data_type: '数据类型',
    permission: '权限',
    gbase_specific: 'GBase 特性',
    cluster_mpp: '集群/MPP',
    performance: '性能',
    import_export: '导入导出',
    license: '授权',
  }
  return map[cat] || cat || '通用'
}
</script>

<template>
  <div class="page-shell errorcode-page">
    <!-- Header -->
    <header class="errorcode-header">
      <div class="header-left">
        <button class="back-btn" @click="router.push('/')">
          <n-icon :component="ArrowBackOutline" size="16" />
          <span>返回</span>
        </button>
        <div class="header-brand">
          <div class="brand-icon">
            <n-icon :component="AlertCircleOutline" size="18" />
          </div>
          <span>错误码查询</span>
        </div>
      </div>
    </header>

    <!-- Main -->
    <div class="errorcode-main">
      <!-- Search -->
      <div class="search-card">
        <div class="search-header">
          <span class="search-label">
            <n-icon :component="CodeSlashOutline" size="14" />
            错误码查询
          </span>
        </div>
        <div class="search-box">
          <n-icon :component="SearchOutline" size="18" class="search-icon" />
          <n-input
            v-model:value="inputText"
            placeholder="如：1064、GBA-2001、连接超时、数据倾斜..."
            :disabled="isLoading"
            @keydown="handleKeydown"
          />
          <button
            class="header-btn primary"
            :class="{ loading: isLoading }"
            :disabled="!inputText.trim()"
            @click="handleSearch()"
          >
            <n-icon :component="SearchOutline" size="14" />
            <span>{{ isLoading ? '查询中...' : '查询' }}</span>
          </button>
        </div>
      </div>

      <!-- Quick queries -->
      <div class="quick-list">
        <span class="quick-label">快捷查询</span>
        <button
          v-for="q in quickQueries"
          :key="q"
          class="quick-pill"
          :disabled="isLoading"
          @click="handleSearch(q)"
        >
          {{ q }}
        </button>
      </div>

      <!-- Result section -->
      <div v-if="lastQuery" class="result-section">
        <div class="result-header">
          <span class="result-query">"{{ lastQuery }}"</span>
          <n-tag v-if="mode" :type="modeType[mode]" size="small" round>{{ modeLabel[mode] }}</n-tag>
          <span v-if="results.length" class="result-count">{{ results.length }} 条结果</span>
        </div>

        <n-spin :show="isLoading">
          <div v-if="results.length === 0 && !isLoading" class="empty-state">
            <n-empty description="未匹配到相关错误码" />
          </div>

          <div v-else class="result-list">
            <article
              v-for="(item, index) in results"
              :key="`${item.code}-${item.score ?? 0}`"
              class="result-card"
              :style="{ animationDelay: `${index * 0.05}s` }"
            >
              <header class="card-head">
                <div class="head-main">
                  <n-icon :component="AlertCircleOutline" size="16" class="head-icon" />
                  <span class="code-label">{{ item.code }}</span>
                </div>
                <div class="head-meta">
                  <span class="category-badge">{{ categoryLabel(item.category) }}</span>
                  <span v-if="item.score !== null" class="score">相关度 {{ (item.score * 100).toFixed(0) }}%</span>
                </div>
              </header>

              <section class="card-body">
                <div class="body-block">
                  <h3 class="block-title">描述</h3>
                  <p class="block-text">{{ item.description }}</p>
                </div>
                <div v-if="item.solution" class="body-block">
                  <h3 class="block-title">解决方案</h3>
                  <pre class="block-pre">{{ item.solution }}</pre>
                </div>
                <div v-if="item.keywords?.length" class="kw-list">
                  <span v-for="kw in item.keywords" :key="kw" class="kw-tag">#{{ kw }}</span>
                </div>
              </section>
            </article>
          </div>
        </n-spin>
      </div>
    </div>
  </div>
</template>

<style scoped>
.errorcode-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ── Header ── */
.errorcode-header {
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

/* ── Main ── */
.errorcode-main {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: 24px;
}

/* ── Search Card ── */
.search-card {
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-lg);
  overflow: hidden;
  margin-bottom: 16px;
  transition: border-color var(--duration-fast);
}
.search-card:hover {
  border-color: var(--seam-2);
}
.search-card:focus-within {
  border-color: var(--text-0);
}

.search-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--seam-1);
  background: var(--bg-surface);
}
.search-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-0);
  letter-spacing: 0.02em;
}
.search-label .n-icon {
  color: var(--text-3);
}

.search-box {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
}
.search-icon {
  color: var(--text-3);
  flex-shrink: 0;
}

.search-box :deep(.n-input) {
  --n-border: none !important;
  --n-border-hover: none !important;
  --n-border-focus: none !important;
  background: transparent !important;
  flex: 1;
}
.search-box :deep(.n-input__border),
.search-box :deep(.n-input__state-border) {
  display: none !important;
}
.search-box :deep(.n-input-wrapper) {
  padding: 0 !important;
  background: transparent !important;
}
.search-box :deep(.n-input__input) {
  font-size: 15px;
  font-weight: 500;
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
  flex-shrink: 0;
}
.header-btn:hover:not(:disabled) {
  background: var(--bg-hover);
  border-color: var(--seam-2);
}
.header-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.header-btn.primary {
  background: var(--text-0);
  border-color: var(--text-0);
  color: var(--bg-void);
}
.header-btn.primary:hover:not(:disabled) {
  background: var(--text-1);
  border-color: var(--text-1);
}

/* ── Quick queries ── */
.quick-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-bottom: 24px;
}
.quick-label {
  font-size: 12px;
  color: var(--text-3);
  font-family: var(--font-mono);
  margin-right: 4px;
}
.quick-pill {
  padding: 5px 12px;
  font-size: 12px;
  font-family: var(--font-mono);
  border-radius: var(--radius-md);
  border: 1px solid var(--seam-1);
  background: var(--bg-panel);
  color: var(--text-2);
  cursor: pointer;
  transition: all var(--duration-fast);
}
.quick-pill:hover:not(:disabled) {
  border-color: var(--seam-2);
  color: var(--text-0);
  background: var(--bg-hover);
}
.quick-pill:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ── Result section ── */
.result-section {
  animation: fadeInUp 0.25s var(--ease-out-expo) both;
}

.result-header {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
  padding: 10px 14px;
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-md);
}
.result-query {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-0);
  font-family: var(--font-mono);
}
.result-count {
  font-size: 12px;
  color: var(--text-3);
  margin-left: auto;
  font-family: var(--font-mono);
}

.result-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* ── Result card ── */
.result-card {
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-lg);
  padding: 18px 20px;
  transition: border-color var(--duration-fast);
  animation: fadeInUp 0.3s var(--ease-out-expo) both;
}
.result-card:hover {
  border-color: var(--seam-2);
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 14px;
  padding-bottom: 12px;
  border-bottom: 1px dashed var(--seam-1);
}
.head-main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.head-icon {
  color: var(--text-2);
  flex-shrink: 0;
}
.code-label {
  font-size: 15px;
  font-weight: 700;
  font-family: var(--font-mono);
  color: var(--text-0);
  letter-spacing: 0.02em;
}
.head-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.category-badge {
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  background: var(--bg-surface);
  color: var(--text-2);
  border: 1px solid var(--seam-1);
  font-size: 11px;
  font-weight: 500;
}
.score {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-3);
}

.card-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.body-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.block-title {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-3);
  font-family: var(--font-mono);
}
.block-text {
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-1);
  margin: 0;
}
.block-pre {
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-1);
  background: var(--bg-deep);
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-md);
  padding: 12px 14px;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font-mono);
}

.kw-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 4px;
}
.kw-tag {
  font-size: 11px;
  color: var(--text-3);
  font-family: var(--font-mono);
}

.empty-state {
  padding: 40px 0;
}

@media (max-width: 768px) {
  .errorcode-header {
    padding: 10px 16px;
  }
  .errorcode-main {
    padding: 16px;
  }
}
</style>
