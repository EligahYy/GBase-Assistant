<script setup lang="ts">
import { onMounted, ref, provide } from 'vue'
import { NMessageProvider, NDialogProvider, NConfigProvider, zhCN, dateZhCN } from 'naive-ui'
import Sidebar from './components/layout/Sidebar.vue'
import { RouterView } from 'vue-router'
import { useConnectionStore } from './stores/connection'
import { useTheme } from './composables/useTheme'

const connStore = useConnectionStore()
const { init: initTheme } = useTheme()
const sidebarOpen = ref(true)
const sidebarCollapsed = ref(false)

provide('toggleSidebar', () => { sidebarOpen.value = !sidebarOpen.value })
provide('sidebarCollapsed', sidebarCollapsed)

onMounted(() => {
  initTheme()
  connStore.loadConnections()
  if (window.innerWidth < 768) sidebarOpen.value = false
})
</script>

<template>
  <n-config-provider :locale="zhCN" :date-locale="dateZhCN">
    <n-dialog-provider>
      <n-message-provider>
        <div class="app-shell">
          <Sidebar
            :open="sidebarOpen"
            :collapsed="sidebarCollapsed"
            @toggle="sidebarOpen = !sidebarOpen"
            @update:collapsed="sidebarCollapsed = $event"
          />
          <main class="main-stage">
            <RouterView />
          </main>
        </div>
      </n-message-provider>
    </n-dialog-provider>
  </n-config-provider>
</template>

<style>
#app, #app > div, #app > div > div, #app > div > div > div {
  height: 100%; width: 100%;
}
</style>

<style scoped>
.app-shell {
  display: flex;
  height: 100%;
  width: 100%;
  overflow: hidden;
  background: var(--bg-body);
}

.main-stage {
  flex: 1;
  min-width: 0;
  height: 100%;
  overflow: hidden;
  position: relative;
}
</style>
