<script setup lang="ts">
import { ref } from 'vue'
import type { ToolCallEntry } from '@/stores/chat'

const props = defineProps<{
  toolCall: ToolCallEntry
}>()

const expanded = ref(false)

const statusIcon: Record<string, string> = {
  running: '🔄',
  done: '✅',
  error: '❌',
  pending: '⏳',
}

const statusText: Record<string, string> = {
  running: '执行中',
  done: '完成',
  error: '失败',
  pending: '等待',
}
</script>

<template>
  <div class="tool-call-card" :class="`status-${toolCall.status}`">
    <button class="tool-call-header" @click="expanded = !expanded">
      <span class="tool-status">{{ statusIcon[toolCall.status] }}</span>
      <span class="tool-name">{{ toolCall.name }}</span>
      <span class="tool-status-text">{{ statusText[toolCall.status] }}</span>
      <span class="tool-chevron">{{ expanded ? '▾' : '▸' }}</span>
    </button>
    <div v-if="expanded" class="tool-call-detail">
      <div v-if="Object.keys(toolCall.args).length" class="tool-args">
        <span class="detail-label">参数:</span>
        <code>{{ JSON.stringify(toolCall.args, null, 2) }}</code>
      </div>
      <div v-if="toolCall.result" class="tool-result">
        <span class="detail-label">结果:</span>
        <span>{{ toolCall.result }}</span>
      </div>
      <div v-if="toolCall.error" class="tool-error">
        <span class="detail-label">错误:</span>
        <span>{{ toolCall.error }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tool-call-card {
  margin: 4px 0 4px 24px;
  font-size: 12px;
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-sm);
  overflow: hidden;
}
.tool-call-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  width: 100%;
  background: var(--bg-panel);
  border: none;
  cursor: pointer;
  font-family: var(--font-sans);
  font-size: 12px;
  color: var(--text-2);
}
.tool-call-header:hover { background: var(--bg-hover); }
.tool-name { font-family: var(--font-mono); color: var(--text-1); font-weight: 500; }
.tool-status-text { color: var(--text-4); font-size: 11px; margin-left: auto; }
.tool-chevron { font-size: 10px; color: var(--text-4); }
.tool-call-detail { padding: 4px 8px 8px; background: var(--bg-deep); }
.tool-args code, .tool-result, .tool-error {
  font-family: var(--font-mono);
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-word;
  display: block;
  margin-top: 2px;
  color: var(--text-2);
}
.tool-error { color: var(--error); }
.detail-label { color: var(--text-4); font-size: 10px; text-transform: uppercase; }
.status-error { border-color: var(--error); }
.status-done { border-color: var(--success); }
</style>
