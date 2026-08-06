<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { clearProxyImageCache, fetchProxyImageCacheStats, purgeProxyImageCache } from '@/api/proxyImageCache'
import { TASK_WRITE } from '@/constants/permissions'
import { useAuthStore } from '@/stores/auth'
import type { ProxyImageCacheStats } from '@/types/proxyImageCache'

const auth = useAuthStore()
const canWrite = computed(() => auth.permissions.includes(TASK_WRITE))

const loading = ref(false)
const stats = ref<ProxyImageCacheStats | null>(null)

function formatBytes(value: number) {
  const bytes = Number(value || 0)
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let num = bytes
  let idx = 0
  while (num >= 1024 && idx < units.length - 1) {
    num /= 1024
    idx += 1
  }
  return `${num.toFixed(idx === 0 ? 0 : 2)} ${units[idx]}`
}

async function loadData() {
  loading.value = true
  try {
    stats.value = await fetchProxyImageCacheStats()
  } finally {
    loading.value = false
  }
}

async function handlePurge() {
  if (!canWrite.value) return
  const out = await purgeProxyImageCache()
  ElMessage.success(`已清理 ${out.deleted_files || 0} 项（${formatBytes(out.deleted_bytes || 0)}）`)
  await loadData()
}

async function handleClear() {
  if (!canWrite.value) return
  await ElMessageBox.confirm('确认清空代理图片缓存目录？', '清空确认', {
    type: 'warning',
    confirmButtonText: '清空',
    cancelButtonText: '取消',
  })
  const out = await clearProxyImageCache()
  ElMessage.success(`已清空 ${out.deleted_files || 0} 项（${formatBytes(out.deleted_bytes || 0)}）`)
  await loadData()
}

onMounted(loadData)
</script>

<template>
  <div class="shell-page">
    <div class="section-header">
      <div class="section-header__title">
        <h2>代理图片缓存</h2>
      </div>
      <div class="toolbar__right">
        <el-button type="primary" @click="loadData">刷新</el-button>
      </div>
    </div>

    <section class="glass-panel table-panel" v-loading="loading">
      <el-descriptions v-if="stats" :column="1" border>
        <el-descriptions-item label="enabled">{{ stats.enabled ? 'true' : 'false' }}</el-descriptions-item>
        <el-descriptions-item label="cache_dir">{{ stats.cache_dir || '-' }}</el-descriptions-item>
        <el-descriptions-item label="ttl_seconds">{{ stats.ttl_seconds }}</el-descriptions-item>
        <el-descriptions-item label="max_file_bytes">{{ formatBytes(stats.max_file_bytes) }}</el-descriptions-item>
        <el-descriptions-item label="max_total_bytes">{{ formatBytes(stats.max_total_bytes) }}</el-descriptions-item>
        <el-descriptions-item label="total_files">{{ stats.total_files }}</el-descriptions-item>
        <el-descriptions-item label="total_bytes">{{ formatBytes(stats.total_bytes) }}</el-descriptions-item>
        <el-descriptions-item label="stale_files">{{ stats.stale_files }}</el-descriptions-item>
      </el-descriptions>
      <el-empty v-else description="暂无数据" />

      <div class="actions">
        <el-button :disabled="!canWrite" @click="handlePurge">清理过期</el-button>
        <el-button type="danger" :disabled="!canWrite" @click="handleClear">一键清空</el-button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.table-panel {
  padding: 18px;
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 16px;
}
</style>

