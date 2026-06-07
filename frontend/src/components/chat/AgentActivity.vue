<script setup lang="ts">
import { ref, watch, onUnmounted } from 'vue'
import type { StreamEvent } from '@/stores/chat'

const props = defineProps<{
  events: StreamEvent[]
  isStreaming: boolean
}>()

const expanded = ref(true)
let collapseTimer: ReturnType<typeof setTimeout> | null = null

// Auto-collapse 2s after streaming ends
watch(() => props.isStreaming, (val) => {
  if (!val && props.events.length > 0) {
    collapseTimer = setTimeout(() => { expanded.value = false }, 2000)
  } else {
    expanded.value = true
  }
})

onUnmounted(() => {
  if (collapseTimer) clearTimeout(collapseTimer)
})

// Map tool names to compact labels
const TOOL_LABEL: Record<string, string> = {
  search_schemas: '搜索表结构',
  get_table_profile: '查看字段',
  find_join_path: '查找关联',
  query_glossary: '查询术语',
  validate_sql: '验证SQL',
  execute_sql: '执行SQL',
  lookup_error: '查询错误码',
  search_knowledge: '检索知识库',
  get_database_status: '获取DB状态',
  delegate_to_sql_specialist: '委托SQL专家',
  delegate_to_knowledge_specialist: '委托知识专家',
  delegate_to_general: '路由到通用Agent',
}

function isToolList(text: string): boolean {
  return /^(调用 \d+ 个工具|搜索相关|查看表|查找表|查询业务|验证 SQL|执行 SQL|查询错误|检索 GBase|获取数据库|委托 SQL|委托知识|处理对话|路由到)/.test(text.trim())
}
</script>

<template>
  <div v-if="events.length > 0" class="agent-activity" :class="{ collapsed: !expanded, streaming: isStreaming }">
    <button class="activity-toggle" @click="expanded = !expanded">
      <span class="toggle-dot" :class="{ active: isStreaming }" />
      <span class="toggle-label">{{ isStreaming ? '正在处理' : '处理过程' }}</span>
      <span class="toggle-chevron">{{ expanded ? '▾' : '▸' }}</span>
    </button>
    <div v-if="expanded" class="activity-body">
      <template v-for="(evt, i) in events" :key="i">
        <!-- Thinking text: only show if it's meaningful (exclude synthetic tool summaries) -->
        <div v-if="evt.type === 'thinking' && evt.thinking && !isToolList(evt.thinking)" class="activity-think">
          {{ evt.thinking }}
        </div>
        <!-- Tool call: compact single-line indicator -->
        <div v-else-if="evt.type === 'tool_call' && evt.toolCall" class="activity-tool" :class="evt.toolCall.status">
          <span class="tool-dot" :class="evt.toolCall.status" />
          <span class="tool-label">{{ TOOL_LABEL[evt.toolCall.name] || evt.toolCall.name }}</span>
          <span v-if="evt.toolCall.status === 'done' && evt.toolCall.result" class="tool-result">
            {{ evt.toolCall.result }}
          </span>
          <span v-else-if="evt.toolCall.status === 'error'" class="tool-error">失败</span>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.agent-activity {
  margin: 4px 0;
  font-size: 12px;
  border-radius: 6px;
  overflow: hidden;
  transition: opacity 0.3s;
}
.agent-activity.collapsed {
  opacity: 0.5;
}
.activity-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 0;
  width: 100%;
  background: none;
  border: none;
  cursor: pointer;
  font-size: 11px;
  color: var(--text-4);
  font-family: var(--font-sans);
}
.activity-toggle:hover { color: var(--text-3); }
.toggle-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-4);
  flex-shrink: 0;
}
.toggle-dot.active {
  background: var(--primary);
  animation: pulse 1.5s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 0.4; }
  50% { opacity: 1; }
}
.toggle-label {
  font-weight: 500;
  letter-spacing: 0.02em;
}
.toggle-chevron { font-size: 9px; margin-left: auto; }
.activity-body {
  padding: 2px 0 2px 16px;
  border-left: 1px solid var(--seam-1);
  margin-left: 3px;
}
.activity-think {
  color: var(--text-3);
  font-size: 11px;
  line-height: 1.5;
  padding: 2px 0;
  font-style: italic;
}
.activity-tool {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 1px 0;
  font-size: 11px;
  color: var(--text-3);
}
.tool-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--text-4);
  flex-shrink: 0;
}
.tool-dot.running {
  background: var(--primary);
  animation: pulse 1s ease-in-out infinite;
}
.tool-dot.done { background: var(--success); }
.tool-dot.error { background: var(--error); }
.tool-label {
  font-weight: 500;
  color: var(--text-2);
}
.tool-result {
  color: var(--text-4);
  font-size: 10px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 180px;
}
.tool-error { color: var(--error); font-size: 10px; }
</style>
