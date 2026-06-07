<script setup lang="ts">
import { ref, watch, computed } from 'vue'

const props = defineProps<{
  thinking: string
  isThinking: boolean
}>()

const expanded = ref(true)
const hasCompleted = ref(false)

watch(() => props.isThinking, (val) => {
  if (val) {
    expanded.value = true
    hasCompleted.value = false
  } else if (props.thinking) {
    // Auto-collapse 1.5s after thinking completes
    setTimeout(() => {
      hasCompleted.value = true
      expanded.value = false
    }, 1500)
  }
})

// Clean up thinking text — remove redundant "调用 N 个工具:" prefix
const cleanThinking = computed(() => {
  let text = props.thinking
  // Remove mechanical tool-call summaries
  text = text.replace(/调用 \d+ 个工具:[\s\S]*$/, '').trim()
  // Remove the explicit tool names list
  text = text.replace(/\n?[📞]?\s*(delegate_to_\w+|search_\w+|get_\w+|find_\w+|validate_\w+|execute_\w+|query_\w+|lookup_\w+)(\s*,\s*)?/g, '')
  return text || props.thinking
})
</script>

<template>
  <div v-if="thinking" class="thinking-section" :class="{ completed: hasCompleted }">
    <button class="thinking-toggle" @click="expanded = !expanded">
      <span class="thinking-dots" v-if="isThinking">
        <span class="dot" v-for="i in 3" :key="i" />
      </span>
      <span class="thinking-label">
        {{ isThinking ? '思考中' : hasCompleted ? '已思考' : '思考过程' }}
      </span>
      <span class="thinking-chevron">{{ expanded ? '▾' : '▸' }}</span>
    </button>
    <div v-if="expanded" class="thinking-content">
      {{ cleanThinking }}
    </div>
  </div>
</template>

<style scoped>
.thinking-section {
  margin: 2px 0;
  font-size: 12px;
  opacity: 0.7;
  transition: opacity 0.3s;
}
.thinking-section.completed {
  opacity: 0.45;
}
.thinking-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 2px 0;
  background: none;
  border: none;
  color: var(--text-4);
  cursor: pointer;
  font-family: var(--font-sans);
  font-size: 11px;
  user-select: none;
}
.thinking-toggle:hover { color: var(--text-3); }
.thinking-dots {
  display: flex;
  gap: 3px;
  align-items: center;
}
.thinking-dots .dot {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--text-4);
  animation: dotPulse 1.4s ease-in-out infinite;
}
.thinking-dots .dot:nth-child(2) { animation-delay: 0.2s; }
.thinking-dots .dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes dotPulse {
  0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
  40% { opacity: 1; transform: scale(1); }
}
.thinking-label {
  font-weight: 500;
  letter-spacing: 0.02em;
}
.thinking-chevron {
  font-size: 9px;
  color: var(--text-4);
}
.thinking-content {
  color: var(--text-3);
  padding: 2px 0 2px 20px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 11px;
  border-left: 1px solid var(--seam-1);
  margin-left: 6px;
}
</style>
