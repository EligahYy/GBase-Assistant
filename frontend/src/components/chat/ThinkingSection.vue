<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  thinking: string
  isThinking: boolean
}>()

const expanded = ref(true)

// Auto-expand while thinking, collapse when done
watch(() => props.isThinking, (val) => {
  if (val) expanded.value = true
})
</script>

<template>
  <div v-if="thinking" class="thinking-section">
    <button class="thinking-toggle" @click="expanded = !expanded">
      <span class="thinking-icon">{{ isThinking ? '🔍' : '💭' }}</span>
      <span class="thinking-label">{{ isThinking ? '思考中...' : '思考过程' }}</span>
      <span class="thinking-chevron">{{ expanded ? '▾' : '▸' }}</span>
    </button>
    <div v-if="expanded" class="thinking-content">
      {{ thinking }}
      <span v-if="isThinking" class="thinking-cursor">|</span>
    </div>
  </div>
</template>

<style scoped>
.thinking-section {
  margin-bottom: 8px;
  font-size: 13px;
}
.thinking-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 0;
  background: none;
  border: none;
  color: var(--text-3);
  cursor: pointer;
  font-family: var(--font-sans);
  font-size: 12px;
}
.thinking-toggle:hover { color: var(--text-2); }
.thinking-icon { font-size: 12px; }
.thinking-label { font-weight: 500; }
.thinking-chevron { font-size: 10px; margin-left: 2px; }
.thinking-content {
  color: var(--text-3);
  font-style: italic;
  padding: 4px 0 4px 24px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}
.thinking-cursor {
  animation: blink 1s step-end infinite;
  font-style: normal;
}
@keyframes blink {
  50% { opacity: 0; }
}
</style>
