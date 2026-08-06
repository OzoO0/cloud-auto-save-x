<script setup lang="ts">
import type { DramaOverview } from '@/types/dashboard'
import { formatPercent } from '@/utils/capacity'

const props = defineProps<{
  overview: DramaOverview
  content?: {
    next7d_count: number
    today_count: number
    with_next_air_date_count: number
  } | null
}>()

function formatDuration(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(value)) return '--'
  const s = Math.max(0, Math.floor(value))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const rs = s % 60
  if (m < 60) return `${m}m ${String(rs).padStart(2, '0')}s`
  const h = Math.floor(m / 60)
  const rm = m % 60
  return `${h}h ${String(rm).padStart(2, '0')}m`
}

const metrics = computed(() => {
  const s = props.overview.summary
  const scheduler = props.overview.scheduler
  const content = props.content || null
  const tmdbHint = s.task_count > 0 ? `${s.tmdb_bound_count}/${s.task_count} 已绑定 TMDB` : '暂无任务'
  const effectiveRuns = (Number(s.execution_success) || 0) + (Number(s.execution_failed) || 0)
  const effectiveSuccessRate = effectiveRuns > 0 ? (Number(s.execution_success) || 0) / effectiveRuns : null

  return [
    {
      label: '启用任务',
      value: `${s.enabled_task_count} / ${s.task_count}`,
      hint: s.unknown_schedule_count ? `有 ${s.unknown_schedule_count} 个启用任务未配置更新日` : '更新日配置完整',
    },
    {
      label: '调度状态',
      value: scheduler.enabled ? '已开启' : '未开启',
      hint: `CRON: ${scheduler.crontab} · ${scheduler.timezone}`,
    },
    {
      label: `近${s.window_days}天成功率`,
      value: formatPercent(effectiveSuccessRate),
      hint: effectiveRuns ? `${effectiveRuns} 次运行` : '暂无执行记录',
    },
    {
      label: '内容进度',
      value: content ? `${content.next7d_count} 部` : '--',
      hint: content ? `今日 ${content.today_count} · 有下次更新日 ${content.with_next_air_date_count}` : tmdbHint,
    },
    {
      label: `平均耗时（近${s.window_days}天）`,
      value: formatDuration(s.avg_duration_s),
      hint: tmdbHint,
    },
  ]
})
</script>

<template>
  <section class="metric-strip drama-hero">
    <div v-for="metric in metrics" :key="metric.label" class="glass-panel metric-tile">
      <div class="metric-tile__label">{{ metric.label }}</div>
      <div class="metric-tile__value">{{ metric.value }}</div>
      <div class="metric-tile__hint">{{ metric.hint }}</div>
    </div>
  </section>
</template>

<style scoped>
.drama-hero {
  grid-template-columns: repeat(5, minmax(0, 1fr));
}

@media (max-width: 1100px) {
  .drama-hero {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
