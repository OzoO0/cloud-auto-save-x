import { defineStore } from 'pinia'

import { getSetupStatus } from '@/api/setup'

export const useSetupStore = defineStore('setup', {
  state: () => ({
    initialized: true as boolean,
    loaded: false as boolean,
    loading: false as boolean,
  }),
  actions: {
    markInitialized() {
      this.initialized = true
      this.loaded = true
    },
    async refreshStatus(force = false) {
      if (this.loading) return
      if (this.loaded && !force) return
      this.loading = true
      try {
        const data = await getSetupStatus()
        this.initialized = Boolean(data.initialized)
        this.loaded = true
      } finally {
        this.loading = false
      }
    },
  },
})

