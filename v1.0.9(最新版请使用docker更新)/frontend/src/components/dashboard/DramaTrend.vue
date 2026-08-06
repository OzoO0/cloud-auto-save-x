<script setup lang="ts">
import type { DramaTrendPoint } from '@/types/dashboard'
import { formatPercent } from '@/utils/capacity'
import EChartsLineChart from '@/components/dashboard/EChartsLineChart.vue'
import { useIsMobile } from '@/composables/useIsMobile'

const props = defineProps<{
  points: DramaTrendPoint[]
}>()

const isMobile = useIsMobile()

function effectiveTotal(p: DramaTrendPoint) {
  return (Number(p.success) || 0) + (Number(p.failed) || 0)
}

const summary = computed(() => {
  const total = props.points.reduce((acc, p) => acc + effectiveTotal(p), 0)
  const success = props.points.reduce((acc, p) => acc + (Number(p.success) || 0), 0)
  const failed = props.points.reduce((acc, p) => acc + (Number(p.failed) || 0), 0)
  const rate = total > 0 ? success / total : 1
  return { total, success, failed, rate }
})

const xLabels = computed(() => {
  return (props.points || []).map((p) => {
    const s = String(p.date || '')
    return s.length >= 10 ? s.slice(5) : s
  })
})

const chartSeries = computed(() => {
  const pts = props.points || []
  return [
    {
      key: 'success',
      name: '成功数',
      color: 'rgba(34, 197, 94, 0.9)',
      axis: 'left' as const,
      values: pts.map((p) => (Number(p.success) || 0) as number),
    },
    {
      key: 'failed',
      name: '失败数',
      color: 'rgba(239, 68, 68, 0.9)',
      axis: 'left' as const,
      values: pts.map((p) => (Number(p.failed) || 0) as number),
    },
    {
      key: 'rate',
      name: '成功率',
      color: 'rgba(37, 99, 235, 0.9)',
      axis: 'right' as const,
      dashed: true,
      values: pts.map((p) => {
        const s = Number(p.success) || 0
        const f = Number(p.failed) || 0
        const t = s + f
        return t > 0 ? s / t : 1
      }),
    },
  ]
})

const chartHeight = computed(() => (isMobile.value ? 220 : 280))
</script>

<template>
  <section class="glass-panel trend-card">
    <div class="section-header">
      <div class="section-header__title">
        <div class="section-header__eyebrow">Trend</div>
        <h2>近期执行趋势</h2>
        <div class="section-header__desc">
          <span>总计 {{ summary.total }} 次</span>
          <span class="sep-dot">·</span>
          <span>成功 {{ summary.success }}</span>
          <span class="sep-dot">·</span>
          <span>失败 {{ summary.failed }}</span>
          <span class="sep-dot">·</span>
          <span>成功率 {{ formatPercent(summary.rate) }}</span>
        </div>
      </div>
    </div>

    <div v-if="points.length" class="trend-chart">
      <EChartsLineChart :x-labels="xLabels" :series="chartSeries" :height="chartHeight" />
    </div>
    <el-empty v-else description="近期开启后尚无执行记录。" :image-size="88" />
  </section>
</template>

<style scoped>
.trend-card {
  padding: 22px;
}

.trend-chart {
  padding-top: 14px;
  overflow-x: auto;
}

.sep-dot {
  margin: 0 6px;
  color: var(--el-text-color-secondary);
}

@media (max-width: 767px) {
  .trend-card {
    padding: 14px;
  }

  .trend-chart {
    padding-top: 10px;
    overflow-x: hidden;
  }
}
</style>
