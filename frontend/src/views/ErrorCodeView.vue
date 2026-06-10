<script setup lang="ts">
import { ref } from 'vue'
import { NInput, NTag, NEmpty, NSpin, useMessage } from 'naive-ui'
import { useRouter } from 'vue-router'
import {
  ArrowBackOutline,
  SearchOutline,
  CodeSlashOutline,
  AlertCircleOutline,
  ChevronDownOutline,
  ChevronUpOutline,
} from '@vicons/ionicons5'
import { NIcon } from 'naive-ui'
import { queryErrorCode, type ErrorCodeItem, type ErrorCodeMode } from '@/api/tools'

const router = useRouter()
const naiveMsg = useMessage()

const expandedIndex = ref<number | null>(null)
function toggleExpand(index: number) {
  expandedIndex.value = expandedIndex.value === index ? null : index
}

const inputText = ref('')
const isLoading = ref(false)
const mode = ref<ErrorCodeMode | null>(null)
const results = ref<ErrorCodeItem[]>([])
const lastQuery = ref('')

const quickQueries = ['GBA-03CR-0001', 'GBA-03GA-0001', 'GBA-02IS-0001', 'GBA-02DU-0001', 'GBA-02DD-0001', 'GBA-02EX-0001', 'gcware 异常', '数据分布', 'insert 错误', '节点故障']

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
    manual: '手册参考',
  }
  return map[cat] || cat || '通用'
}
</script>

<template>
  <div class="page-shell errorcode-page">
    <!-- Main -->
    <div class="errorcode-main">
      <!-- Hero -->
      <div class="errorcode-hero">
        <h1 class="hero-title">错误码查询</h1>
        <p class="hero-sub">输入 GBase 8a 错误码或关键词，获取详细解决方案</p>
      </div>

      <!-- Search -->
      <div class="search-wrap">
        <div class="search-box">
          <n-icon :component="SearchOutline" size="20" class="search-icon" />
          <n-input
            v-model:value="inputText"
            placeholder="搜索错误码或关键词，如 1146、连接超时..."
            :disabled="isLoading"
            @keydown="handleKeydown"
          />
          <span class="search-hint">Enter 搜索</span>
        </div>
      </div>

      <!-- Quick queries -->
      <div class="quick-list">
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
              <header class="card-head" @click="toggleExpand(index)" style="cursor:pointer;">
                <div class="head-main">
                  <n-icon :component="AlertCircleOutline" size="16" class="head-icon" />
                  <span class="code-label">{{ item.code }}</span>
                </div>
                <div class="head-meta">
                  <span class="category-badge">{{ categoryLabel(item.category) }}</span>
                  <span v-if="item.score !== null" class="score">相关度 {{ (item.score * 100).toFixed(0) }}%</span>
                  <n-icon
                    :component="expandedIndex === index ? ChevronUpOutline : ChevronDownOutline"
                    size="16"
                    style="color:var(--text-3);flex-shrink:0;"
                  />
                </div>
              </header>

              <section v-show="expandedIndex === index" class="card-body">
                <div class="body-block">
                  <h3 class="block-title">{{ item.code === '手册参考' ? '手册章节' : '描述' }}</h3>
                  <p class="block-text">{{ item.description }}</p>
                </div>
                <div v-if="item.solution" class="body-block">
                  <h3 class="block-title">{{ item.code === '手册参考' ? '手册内容' : '解决方案' }}</h3>
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
  height: 100vh; display: flex; flex-direction: column; overflow: hidden;
  background: #fafafa;
}
.errorcode-main {
  flex: 1; min-width: 0; overflow-y: auto;
  max-width: 800px; margin: 0 auto; padding: 48px 28px 80px;
}

/* ── Hero ── */
.errorcode-hero { text-align: center; margin-bottom: 32px; }
.hero-title { font-size: 26px; font-weight: 700; color: #111; letter-spacing: -0.02em; margin-bottom: 8px; }
.hero-sub { font-size: 14px; color: #999; }

/* ── Search ── */
.search-wrap { max-width: 560px; margin: 0 auto 24px; }
.search-box {
  display: flex; align-items: center; gap: 10px;
  padding: 12px 16px; background: #fff;
  border: 1.5px solid #e0e0e0; border-radius: 14px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.04);
  transition: border-color 0.15s;
}
.search-box:focus-within { border-color: #aaa; }
.search-icon { color: #bbb; flex-shrink: 0; }
.search-hint {
  font-size: 10px; color: #bbb; background: #f4f4f4;
  padding: 3px 8px; border-radius: 6px; font-family: monospace;
  flex-shrink: 0;
}
.search-box :deep(.n-input) {
  --n-border: none !important; --n-border-hover: none !important; --n-border-focus: none !important;
  background: transparent !important; flex: 1;
}
.search-box :deep(.n-input__border), .search-box :deep(.n-input__state-border) { display: none !important; }
.search-box :deep(.n-input-wrapper) { padding: 0 !important; background: transparent !important; }
.search-box :deep(.n-input__input) { font-size: 14px; }

/* ── Quick queries ── */
.quick-list { display: flex; flex-wrap: wrap; gap: 6px; justify-content: center; margin-bottom: 28px; }
.quick-pill {
  padding: 5px 12px; font-size: 11px; font-family: var(--font-mono);
  border-radius: 6px; border: 1px solid #e8e8e8; background: #fff;
  color: #888; cursor: pointer; transition: all 0.15s;
}
.quick-pill:hover:not(:disabled) { border-color: #aaa; color: #111; }
.quick-pill:disabled { opacity: 0.5; cursor: not-allowed; }

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
  background: #fff;
  border: 1px solid #eee;
  border-radius: 14px;
  padding: 16px 20px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.03);
  transition: border-color 0.15s;
  animation: fadeInUp 0.3s var(--ease-out-expo) both;
}
.result-card:hover { border-color: #ccc; }

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
  font-size: 13px;
  font-weight: 700;
  font-family: var(--font-mono);
  background: #fef7ed;
  color: #d97706;
  padding: 4px 10px;
  border-radius: 8px;
  border: 1px solid #fde68a;
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
