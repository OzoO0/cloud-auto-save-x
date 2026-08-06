<script setup lang="ts">
import type { CapacitySummary } from '@/types/dashboard'
import { formatBytes, formatPercent } from '@/utils/capacity'

const props = defineProps<{
  summary: CapacitySummary
}>()

const metrics = computed(() => [
  {
    label: '总容量',
    value: formatBytes(props.summary.total_space),
    hint: `${props.summary.capacity_account_count} 个账号可统计`,
  },
  {
    label: '已使用',
    value: formatBytes(props.summary.total_used_space),
    hint: '基于最近一次容量快照',
  },
  {
    label: '整体占比',
    value: formatPercent(props.summary.usage_ratio),
    hint: props.summary.total_space ? '所有支持容量的网盘汇总' : '暂无容量数据',
  },
  {
    label: '预警账号',
    value: String(props.summary.warning_account_count),
    hint: `${props.summary.account_count} 个账号中需要关注`,
  },
])
</script>

<template>
  <section class="metric-strip">
    <div v-for="metric in metrics" :key="metric.label" class="glass-panel metric-tile">
      <div class="metric-tile__label">{{ metric.label }}</div>
      <div class="metric-tile__value">{{ metric.value }}</div>
      <div class="metric-tile__hint">{{ metric.hint }}</div>
    </div>
  </section>
</template>
