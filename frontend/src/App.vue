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

/* Starfield background */
.app-shell::before {
  content: '';
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background:
    radial-gradient(1px 1px at 20px 30px, rgba(45,212,191,0.15), transparent),
    radial-gradient(1px 1px at 40px 70px, rgba(45,212,191,0.08), transparent),
    radial-gradient(1px 1px at 50px 160px, rgba(255,255,255,0.06), transparent),
    radial-gradient(1px 1px at 90px 40px, rgba(45,212,191,0.10), transparent),
    radial-gradient(1px 1px at 130px 80px, rgba(255,255,255,0.04), transparent),
    radial-gradient(1px 1px at 160px 120px, rgba(45,212,191,0.06), transparent),
    radial-gradient(1.5px 1.5px at 200px 50px, rgba(255,255,255,0.08), transparent),
    radial-gradient(1px 1px at 250px 180px, rgba(45,212,191,0.05), transparent),
    radial-gradient(1px 1px at 300px 90px, rgba(255,255,255,0.04), transparent),
    radial-gradient(1px 1px at 350px 150px, rgba(45,212,191,0.07), transparent),
    radial-gradient(1.5px 1.5px at 400px 60px, rgba(255,255,255,0.06), transparent),
    radial-gradient(1px 1px at 450px 200px, rgba(45,212,191,0.04), transparent),
    radial-gradient(1px 1px at 500px 110px, rgba(255,255,255,0.05), transparent),
    radial-gradient(1px 1px at 550px 170px, rgba(45,212,191,0.06), transparent),
    radial-gradient(1px 1px at 600px 80px, rgba(255,255,255,0.04), transparent),
    radial-gradient(1.5px 1.5px at 650px 140px, rgba(45,212,191,0.08), transparent),
    radial-gradient(1px 1px at 700px 190px, rgba(255,255,255,0.05), transparent),
    radial-gradient(1px 1px at 750px 100px, rgba(45,212,191,0.06), transparent),
    radial-gradient(1px 1px at 800px 160px, rgba(255,255,255,0.04), transparent),
    radial-gradient(1.5px 1.5px at 850px 70px, rgba(45,212,191,0.07), transparent),
    radial-gradient(1px 1px at 900px 130px, rgba(255,255,255,0.05), transparent),
    radial-gradient(1px 1px at 950px 180px, rgba(45,212,191,0.05), transparent),
    radial-gradient(1px 1px at 1000px 90px, rgba(255,255,255,0.06), transparent);
}

html[data-theme="light"] .app-shell::before {
  background:
    radial-gradient(1px 1px at 20px 30px, rgba(13,148,136,0.08), transparent),
    radial-gradient(1px 1px at 40px 70px, rgba(13,148,136,0.04), transparent),
    radial-gradient(1px 1px at 50px 160px, rgba(0,0,0,0.03), transparent),
    radial-gradient(1px 1px at 90px 40px, rgba(13,148,136,0.06), transparent),
    radial-gradient(1px 1px at 130px 80px, rgba(0,0,0,0.02), transparent);
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
