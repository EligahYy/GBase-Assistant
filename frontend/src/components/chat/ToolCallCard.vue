<script setup lang="ts">
import { computed } from 'vue'
import type { ToolCallEntry } from '@/stores/chat'

const props = defineProps<{
  toolCall: ToolCallEntry
}>()

// Human-readable labels — no raw tool names visible to users
const TOOL_LABELS: Record<string, { icon: string; action: string }> = {
  search_schemas: { icon: '🔍', action: '搜索数据库表结构' },
  get_table_profile: { icon: '📋', action: '查看表字段详情' },
  find_join_path: { icon: '🔗', action: '查找表关联关系' },
  query_glossary: { icon: '📖', action: '查询业务术语映射' },
  validate_sql: { icon: '✅', action: '验证 SQL 语法' },
  execute_sql: { icon: '⚡', action: '执行 SQL 查询' },
  lookup_error: { icon: '🐛', action: '查询错误码含义' },
  search_knowledge: { icon: '📚', action: '检索 GBase 8a 知识库' },
  get_database_status: { icon: '📊', action: '获取数据库运行状态' },
  delegate_to_sql_specialist: { icon: '🤖', action: '调用 SQL 专家处理' },
  delegate_to_knowledge_specialist: { icon: '📚', action: '调用知识专家处理' },
  delegate_to_general: { icon: '💬', action: '处理对话' },
}

const label = computed(() =>
  TOOL_LABELS[props.toolCall.name] || { icon: '🔧', action: props.toolCall.name }
)

const resultSummary = computed(() => {
  if (props.toolCall.status === 'error') return props.toolCall.error || '执行失败'
  if (props.toolCall.status === 'done' && props.toolCall.result) return props.toolCall.result
  return ''
})
</script>

<template>
  <div class="tool-call" :class="`status-${toolCall.status}`">
    <span class="tool-icon">{{ label.icon }}</span>
    <span class="tool-action">{{ label.action }}</span>
    <span v-if="toolCall.status === 'running'" class="tool-spinner" />
    <span v-else-if="toolCall.status === 'error'" class="tool-status-mark error-mark">✗</span>
    <span v-else class="tool-status-mark done-mark">✓</span>
    <span v-if="resultSummary" class="tool-result">{{ resultSummary }}</span>
  </div>
</template>

<style scoped>
.tool-call {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 0;
  font-size: 12px;
  color: var(--text-3);
  margin-left: 8px;
}
.tool-call.status-error {
  color: var(--error);
}
.tool-icon {
  font-size: 13px;
  flex-shrink: 0;
}
.tool-action {
  font-weight: 500;
  color: var(--text-2);
}
.tool-spinner {
  width: 11px;
  height: 11px;
  border: 1.5px solid var(--seam-2);
  border-top-color: var(--text-2);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  flex-shrink: 0;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
.tool-status-mark {
  font-size: 10px;
  flex-shrink: 0;
  font-weight: 700;
}
.done-mark { color: var(--success); }
.error-mark { color: var(--error); }
.tool-result {
  color: var(--text-4);
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 240px;
  margin-left: 2px;
}
</style>
