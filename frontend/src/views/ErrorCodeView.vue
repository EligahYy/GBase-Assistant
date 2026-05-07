<script setup lang="ts">
import { ref } from 'vue'
import { NInput, NButton, NTag, NEmpty, NSpin, useMessage } from 'naive-ui'
import { useRouter } from 'vue-router'
import { ArrowBackOutline, SearchOutline, CodeSlashOutline } from '@vicons/ionicons5'
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
      naiveMsg.info('未匹配到相关错误码,可换个关键词试试')
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
  <div class="error-page">
    <div class="error-inner">
      <button class="back-link" @click="router.push('/')">
        <n-icon :component="ArrowBackOutline" size="16" />
        <span>返回</span>
      </button>

      <h1 class="page-title">错误码查询</h1>
      <p class="page-desc">输入 GBase 8a 错误码或自然语言关键词,系统返回原因与解决方案</p>

      <!-- Search bar -->
      <div class="search-box">
        <n-icon :component="SearchOutline" size="18" class="search-icon" />
        <n-input
          v-model:value="inputText"
          placeholder="如:1064、GBA-2001、连接超时、数据倾斜..."
          :disabled="isLoading"
          @keydown="handleKeydown"
        />
        <n-button type="primary" :loading="isLoading" @click="handleSearch()">查询</n-button>
      </div>

      <!-- Quick queries -->
      <div class="quick-list">
        <span class="quick-label">快捷查询:</span>
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
          <div v-if="results.length === 0 && !isLoading" class="empty-wrap">
            <n-empty description="未匹配到相关错误码" />
          </div>

          <div v-else class="result-list">
            <article v-for="item in results" :key="`${item.code}-${item.score ?? 0}`" class="result-card">
              <header class="card-head">
                <div class="head-main">
                  <n-icon :component="CodeSlashOutline" size="16" class="head-icon" />
                  <span class="code-label">{{ item.code }}</span>
                </div>
                <div class="head-meta">
                  <n-tag size="small" round>{{ categoryLabel(item.category) }}</n-tag>
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
.error-page {
  height: 100%;
  overflow-y: auto;
  background: var(--bg-body);
}
.error-inner {
  max-width: 760px;
  margin: 0 auto;
  padding: 48px 24px 80px;
}
@media (max-width: 768px) {
  .error-inner { padding: 32px 20px 60px; }
}

.back-link {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 14px; color: var(--text-secondary, var(--text-3));
  background: none; border: none; cursor: pointer;
  margin-bottom: 20px;
  transition: color var(--duration-fast) var(--ease-smooth);
}
.back-link:hover { color: var(--text-primary, var(--text-0)); }

.page-title {
  font-size: var(--text-2xl, 26px); font-weight: 600;
  color: var(--text-primary, var(--text-0)); letter-spacing: -0.03em;
  margin-bottom: 6px;
}
.page-desc {
  color: var(--text-secondary, var(--text-3));
  font-size: 14px;
  margin-bottom: 28px;
}

.search-box {
  display: flex; align-items: center; gap: 10px;
  padding: 6px 6px 6px 14px;
  background: var(--bg-surface, var(--bg-panel));
  border: 1px solid var(--border, var(--seam-2));
  border-radius: var(--radius-lg, 16px);
  margin-bottom: 14px;
  transition: border-color var(--duration-fast);
}
.search-box:focus-within { border-color: var(--accent-bright, var(--accent)); }
.search-icon { color: var(--text-muted, var(--text-4)); flex-shrink: 0; }
.search-box :deep(.n-input) {
  --n-border: none !important;
  --n-border-hover: none !important;
  --n-border-focus: none !important;
  background: transparent !important;
}
.search-box :deep(.n-input__border),
.search-box :deep(.n-input__state-border) { display: none !important; }
.search-box :deep(.n-input-wrapper) { padding: 0 !important; background: transparent !important; }

.quick-list {
  display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
  margin-bottom: 32px;
}
.quick-label {
  font-size: 12px; color: var(--text-muted, var(--text-4));
  font-family: var(--font-mono, monospace);
  margin-right: 4px;
}
.quick-pill {
  padding: 4px 12px;
  border-radius: 100px;
  border: 1px solid var(--seam-1, var(--border));
  background: var(--bg-panel, var(--bg-surface));
  color: var(--text-3, var(--text-secondary));
  font-size: 12px;
  font-family: var(--font-mono, monospace);
  cursor: pointer;
  transition: all var(--duration-fast);
}
.quick-pill:hover:not(:disabled) {
  border-color: var(--seam-2, var(--accent-dim));
  color: var(--text-1, var(--text-primary));
}
.quick-pill:disabled { opacity: 0.5; cursor: not-allowed; }

.result-section { margin-top: 8px; }
.result-header {
  display: flex; align-items: center; gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 18px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--seam-1, var(--divider));
}
.result-query {
  font-size: 16px; font-weight: 600;
  color: var(--text-0, var(--text-primary));
  font-family: var(--font-mono, monospace);
}
.result-count {
  font-size: 12px; color: var(--text-muted, var(--text-4));
}

.result-list {
  display: flex; flex-direction: column; gap: 16px;
}

.result-card {
  background: var(--bg-surface, var(--bg-panel));
  border: 1px solid var(--seam-1, var(--border));
  border-radius: var(--radius-lg, 16px);
  padding: 18px 20px;
  transition: border-color var(--duration-fast);
}
.result-card:hover { border-color: var(--seam-2, var(--accent-dim)); }

.card-head {
  display: flex; align-items: center; justify-content: space-between;
  gap: 10px; flex-wrap: wrap;
  margin-bottom: 14px;
  padding-bottom: 12px;
  border-bottom: 1px dashed var(--seam-1, var(--divider));
}
.head-main { display: flex; align-items: center; gap: 8px; min-width: 0; }
.head-icon { color: var(--accent, currentColor); flex-shrink: 0; }
.code-label {
  font-size: 16px; font-weight: 700;
  font-family: var(--font-mono, monospace);
  color: var(--accent, var(--text-0));
  letter-spacing: 0.02em;
}
.head-meta {
  display: flex; align-items: center; gap: 8px;
  font-size: 12px; color: var(--text-muted, var(--text-4));
}
.score {
  font-family: var(--font-mono, monospace);
  font-size: 11px;
}

.card-body {
  display: flex; flex-direction: column; gap: 14px;
}
.body-block {
  display: flex; flex-direction: column; gap: 6px;
}
.block-title {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted, var(--text-4));
  font-family: var(--font-mono, monospace);
}
.block-text {
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-1, var(--text-primary));
  margin: 0;
}
.block-pre {
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-1, var(--text-primary));
  background: var(--bg-panel, var(--bg-surface));
  border: 1px solid var(--seam-1, var(--divider));
  border-radius: var(--radius-md, 10px);
  padding: 12px 14px;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font-mono, monospace);
}

.kw-list {
  display: flex; flex-wrap: wrap; gap: 6px;
  margin-top: 4px;
}
.kw-tag {
  font-size: 11px;
  color: var(--text-muted, var(--text-4));
  font-family: var(--font-mono, monospace);
}

.empty-wrap { padding: 40px 0; }
</style>
