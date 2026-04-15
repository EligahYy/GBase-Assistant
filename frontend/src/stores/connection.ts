import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ConnectionResponse } from '@/api/connections'
import { listConnections } from '@/api/connections'

export const useConnectionStore = defineStore('connection', () => {
  const connections = ref<ConnectionResponse[]>([])
  const activeConnectionId = ref<string | null>(null)

  async function loadConnections() {
    connections.value = await listConnections()
    if (!activeConnectionId.value && connections.value.length > 0) {
      activeConnectionId.value = connections.value[0]?.id ?? null
    }
  }

  function setActiveConnection(id: string | null) {
    activeConnectionId.value = id
  }

  return { connections, activeConnectionId, loadConnections, setActiveConnection }
})
