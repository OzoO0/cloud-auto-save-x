<script setup lang="ts">
import { ElMessage } from 'element-plus'

import PluginCard from '@/components/extensions/PluginCard.vue'
import PluginConfigDrawer from '@/components/extensions/PluginConfigDrawer.vue'
import { fetchPlugins, fetchSyncPlugins, refreshPlugins, refreshSyncPlugins, updatePlugin, updateSyncPlugin } from '@/api/extensions'
import { PLUGIN_WRITE } from '@/constants/permissions'
import { useAuthStore } from '@/stores/auth'
import type { PluginItem } from '@/types/extensions'

const auth = useAuthStore()
const canWrite = computed(() => auth.permissions.includes(PLUGIN_WRITE))

const loading = ref(false)
const submitting = ref(false)
const refreshing = ref(false)
const plugins = ref<PluginItem[]>([])
const drawerVisible = ref(false)
const currentPlugin = ref<PluginItem | null>(null)
const activeTab = ref<'task' | 'sync'>('task')

const summary = computed(() => ({
  total: plugins.value.length,
  enabled: plugins.value.filter((item) => item.enabled).length,
  error: plugins.value.filter((item) => item.runtime_status === 'error').length,
}))

function pickApi() {
  if (activeTab.value === 'sync') {
    return { fetch: fetchSyncPlugins, refresh: refreshSyncPlugins, update: updateSyncPlugin }
  }
  return { fetch: fetchPlugins, refresh: refreshPlugins, update: updatePlugin }
}

async function loadData() {
  loading.value = true
  try {
    plugins.value = await pickApi().fetch()
  } finally {
    loading.value = false
  }
}

function openEditDrawer(row: PluginItem) {
  currentPlugin.value = row
  drawerVisible.value = true
}

async function handleRefresh() {
  refreshing.value = true
  try {
    plugins.value = await pickApi().refresh()
    ElMessage.success('插件扫描已刷新')
  } finally {
    refreshing.value = false
  }
}

async function handleToggle(row: PluginItem, enabled: boolean) {
  await pickApi().update(row.plugin_key, { enabled })
  ElMessage.success('插件状态已更新')
  await loadData()
}

async function submitForm(payload: { enabled: boolean; priority: number; config: Record<string, any> }) {
  if (!currentPlugin.value) return
  submitting.value = true
  try {
    await pickApi().update(currentPlugin.value.plugin_key, payload)
    drawerVisible.value = false
    ElMessage.success('插件配置已更新')
    await loadData()
  } finally {
    submitting.value = false
  }
}

watch(
  activeTab,
  async () => {
    drawerVisible.value = false
    currentPlugin.value = null
    await loadData()
  },
  { immediate: false },
)

onMounted(loadData)
</script>

<template>
  <div class="shell-page" v-loading="loading">
    <div class="section-header">
      <div class="section-header__title">
        <h2>插件管理</h2>
      </div>
      <div class="toolbar__right">
        <el-button type="primary" @click="loadData">刷新列表</el-button>
        <el-button v-if="canWrite" :loading="refreshing" type="success" @click="handleRefresh">扫描插件</el-button>
      </div>
    </div>

    <el-tabs v-model="activeTab" style="margin-bottom: 12px">
      <el-tab-pane name="task" label="追剧任务插件" />
      <el-tab-pane name="sync" label="同步任务插件" />
    </el-tabs>

    <section class="metric-strip">
      <div class="glass-panel metric-tile">
        <div class="metric-tile__label">插件总数</div>
        <div class="metric-tile__value">{{ summary.total }}</div>
        <div class="metric-tile__hint">当前可发现的插件模块</div>
      </div>
      <div class="glass-panel metric-tile">
        <div class="metric-tile__label">启用插件</div>
        <div class="metric-tile__value">{{ summary.enabled }}</div>
        <div class="metric-tile__hint">已参与运行的插件</div>
      </div>
      <div class="glass-panel metric-tile">
        <div class="metric-tile__label">异常插件</div>
        <div class="metric-tile__value">{{ summary.error }}</div>
        <div class="metric-tile__hint">最近一次运行状态异常</div>
      </div>
    </section>

    <section v-if="plugins.length" class="plugin-grid">
      <PluginCard
        v-for="plugin in plugins"
        :key="plugin.plugin_key"
        :plugin="plugin"
        :can-write="canWrite"
        @configure="openEditDrawer"
        @toggle="handleToggle"
      />
    </section>

    <section v-else class="glass-panel dashboard-section">
      <div class="empty-copy">暂无插件数据，可先执行一次插件扫描。</div>
    </section>

    <PluginConfigDrawer
      v-model="drawerVisible"
      :plugin="currentPlugin"
      :submitting="submitting"
      @save="submitForm"
    />
  </div>
</template>

<style scoped>
.plugin-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 18px;
}

@media (max-width: 768px) {
  .plugin-grid {
    grid-template-columns: 1fr;
  }
}
</style>
