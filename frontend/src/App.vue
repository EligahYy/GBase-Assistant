<script setup lang="ts">
import { onMounted, ref, watch, provide } from 'vue'
import { NMessageProvider, NDialogProvider, NConfigProvider, zhCN, dateZhCN } from 'naive-ui'
import Sidebar from './components/layout/Sidebar.vue'
import { RouterView } from 'vue-router'
import { useConnectionStore } from './stores/connection'
import { useTheme } from './composables/useTheme'

const connStore = useConnectionStore()
const { init: initTheme } = useTheme()

const STORAGE_KEY = 'sidebar:collapsed'
const sidebarCollapsed = ref(false)

// Restore collapsed state
if (typeof window !== 'undefined') {
  try {
    sidebarCollapsed.value = localStorage.getItem(STORAGE_KEY) === '1'
  } catch {}
}

watch(sidebarCollapsed, (val) => {
  try { localStorage.setItem(STORAGE_KEY, val ? '1' : '0') } catch {}
})

provide('toggleSidebar', () => { sidebarCollapsed.value = !sidebarCollapsed.value })
provide('sidebarCollapsed', sidebarCollapsed)

function handleKeydown(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'b') {
    const target = e.target as HTMLElement | null
    if (target && (
      target.tagName === 'INPUT' ||
      target.tagName === 'TEXTAREA' ||
      target.isContentEditable
    )) return
    e.preventDefault()
    sidebarCollapsed.value = !sidebarCollapsed.value
  }
}

onMounted(() => {
  initTheme()
  connStore.loadConnections()
  connStore.startStatusStream()  // 全局启动 SSE 连接状态推送
  window.addEventListener('keydown', handleKeydown)
})
</script>

<template>
  <n-config-provider :locale="zhCN" :date-locale="dateZhCN">
    <n-dialog-provider>
      <n-message-provider>
        <div class="app-shell">
          <Sidebar
            :collapsed="sidebarCollapsed"
            @update:collapsed="sidebarCollapsed = $event"
          />
          <main
            class="main-stage"
            :class="{ 'sidebar-collapsed': sidebarCollapsed }"
          >
            <RouterView />
          </main>
        </div>
      </n-message-provider>
    </n-dialog-provider>
  </n-config-provider>
</template>

<style>
#app, #app > div, #app > div > div, #app > div > div > div {
  height: 100%;
  width: 100%;
}
</style>

<style scoped>
.app-shell {
  display: flex;
  height: 100%;
  width: 100%;
  overflow: hidden;
  background: var(--bg-void);
  position: relative;
}


.main-stage {
  flex: 1;
  min-width: 0;
  height: 100%;
  overflow: hidden;
  position: relative;
  z-index: 1;
  margin-left: var(--sidebar-width);
  transition: margin-left var(--duration-normal) var(--ease-smooth);
}
.main-stage.sidebar-collapsed {
  margin-left: 48px;
}
@media (max-width: 768px) {
  .main-stage {
    margin-left: 0 !important;
  }
}
</style>
