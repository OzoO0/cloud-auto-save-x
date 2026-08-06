<script setup lang="ts">
type AxisKey = 'left' | 'right'

type Series = {
  key: string
  name: string
  color: string
  axis: AxisKey
  values: Array<number | null>
  dashed?: boolean
}

const props = withDefaults(
  defineProps<{
    xLabels: string[]
    series: Series[]
    height?: number
  }>(),
  {
    height: 260,
  },
)

const enabledKeys = ref<Set<string>>(new Set(props.series.map((s) => s.key)))

watch(
  () => props.series,
  (val) => {
    const next = new Set<string>()
    for (const s of val) {
      if (enabledKeys.value.has(s.key)) next.add(s.key)
    }
    if (!next.size) {
      for (const s of val) next.add(s.key)
    }
    enabledKeys.value = next
  },
  { deep: true },
)

const wrapper = ref<HTMLElement | null>(null)
const hoverIndex = ref<number | null>(null)
const pointer = reactive({ x: 0, y: 0 })

const w = 860
const h = computed(() => Math.max(180, Number(props.height) || 260))
const padX = 42
const padY = 18

const visibleSeries = computed(() => props.series.filter((s) => enabledKeys.value.has(s.key)))

function clamp(n: number, min: number, max: number) {
  return Math.max(min, Math.min(max, n))
}

const xCount = computed(() => props.xLabels.length)
const stepX = computed(() => {
  const denom = Math.max(1, xCount.value - 1)
  return (w - padX * 2) / denom
})

function xAt(index: number) {
  return padX + stepX.value * index
}

const leftMax = computed(() => {
  let maxVal = 0
  for (const s of visibleSeries.value) {
    if (s.axis !== 'left') continue
    for (const v of s.values) {
      if (v == null) continue
      if (!Number.isFinite(v)) continue
      maxVal = Math.max(maxVal, v)
    }
  }
  return Math.max(1, maxVal)
})

function yLeft(v: number) {
  const innerH = h.value - padY * 2
  return padY + innerH - (innerH * v) / leftMax.value
}

function yRight(v: number) {
  const innerH = h.value - padY * 2
  const clamped = clamp(v, 0, 1)
  return padY + innerH - innerH * clamped
}

function yFor(axis: AxisKey, v: number) {
  return axis === 'right' ? yRight(v) : yLeft(v)
}

function pathFor(s: Series) {
  const parts: string[] = []
  const len = Math.min(xCount.value, s.values.length)
  for (let i = 0; i < len; i += 1) {
    const v = s.values[i]
    if (v == null || !Number.isFinite(v)) continue
    const x = xAt(i)
    const y = yFor(s.axis, v)
    parts.push(parts.length ? `L ${x.toFixed(1)} ${y.toFixed(1)}` : `M ${x.toFixed(1)} ${y.toFixed(1)}`)
  }
  return parts.join(' ')
}

function handleMouseMove(evt: MouseEvent) {
  const el = wrapper.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const x = evt.clientX - rect.left
  const y = evt.clientY - rect.top
  pointer.x = x
  pointer.y = y
  const idx = Math.round((x - padX) / stepX.value)
  hoverIndex.value = clamp(idx, 0, Math.max(0, xCount.value - 1))
}

function handleMouseLeave() {
  hoverIndex.value = null
}

function formatValue(axis: AxisKey, value: number | null) {
  if (value == null || !Number.isFinite(value)) return '--'
  if (axis === 'right') return `${(value * 100).toFixed(value >= 0.1 ? 1 : 2)}%`
  return String(Math.round(value))
}

const tooltip = computed(() => {
  const idx = hoverIndex.value
  if (idx == null) return null
  const label = props.xLabels[idx] || ''
  const rows = visibleSeries.value.map((s) => {
    const v = idx < s.values.length ? s.values[idx] : null
    return { key: s.key, name: s.name, color: s.color, value: formatValue(s.axis, v) }
  })
  return { label, rows }
})

const tooltipStyle = computed(() => {
  const x = clamp(pointer.x + 12, 8, w - 240)
  const y = clamp(pointer.y + 12, 8, h.value - 120)
  return {
    transform: `translate(${x}px, ${y}px)`,
  }
})

const hoverDots = computed(() => {
  const idx = hoverIndex.value
  if (idx == null) return []
  return visibleSeries.value
    .map((s) => {
      const v = idx < s.values.length ? s.values[idx] : null
      if (v == null || !Number.isFinite(v)) return null
      return { key: s.key, color: s.color, cx: xAt(idx), cy: yFor(s.axis, v) }
    })
    .filter(Boolean) as Array<{ key: string; color: string; cx: number; cy: number }>
})

function toggleSeries(key: string) {
  const next = new Set(enabledKeys.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  if (!next.size) return
  enabledKeys.value = next
}
</script>

<template>
  <div ref="wrapper" class="chart">
    <div class="legend">
      <button
        v-for="s in series"
        :key="s.key"
        class="legend__item"
        type="button"
        :class="enabledKeys.has(s.key) ? 'is-on' : 'is-off'"
        @click="toggleSeries(s.key)"
      >
        <span class="legend__dot" :style="{ background: s.color }"></span>
        <span class="legend__name">{{ s.name }}</span>
      </button>
    </div>

    <div class="plot" @mousemove="handleMouseMove" @mouseleave="handleMouseLeave">
      <svg :viewBox="`0 0 ${w} ${h}`" class="svg" :style="{ height: `${h}px` }">
        <g class="grid">
          <line :x1="padX" :y1="h - padY" :x2="w - padX" :y2="h - padY" />
          <line :x1="padX" :y1="padY" :x2="padX" :y2="h - padY" />
          <line :x1="w - padX" :y1="padY" :x2="w - padX" :y2="h - padY" />
        </g>

        <g v-if="hoverIndex != null" class="crosshair">
          <line :x1="xAt(hoverIndex)" :y1="padY" :x2="xAt(hoverIndex)" :y2="h - padY" />
        </g>

        <g class="lines">
          <path
            v-for="s in visibleSeries"
            :key="s.key"
            class="line"
            :style="{ stroke: s.color, strokeDasharray: s.dashed ? '7 7' : undefined }"
            :d="pathFor(s)"
          />
        </g>

        <g v-if="hoverIndex != null" class="dots">
          <circle
            v-for="d in hoverDots"
            :key="`dot-${d.key}`"
            class="dot"
            :style="{ fill: d.color }"
            :cx="d.cx"
            :cy="d.cy"
            r="4"
          />
        </g>

        <g class="xlabels">
          <text
            v-for="(label, idx) in xLabels"
            :key="`x-${idx}`"
            :x="xAt(idx)"
            :y="h - 4"
            text-anchor="middle"
          >
            {{ label }}
          </text>
        </g>
      </svg>

      <div v-if="tooltip" class="tooltip" :style="tooltipStyle">
        <div class="tooltip__title">{{ tooltip.label }}</div>
        <div class="tooltip__rows">
          <div v-for="row in tooltip.rows" :key="row.key" class="tooltip__row">
            <span class="tooltip__dot" :style="{ background: row.color }"></span>
            <span class="tooltip__name">{{ row.name }}</span>
            <span class="tooltip__value">{{ row.value }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chart {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.legend {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.legend__item {
  appearance: none;
  border: 1px solid var(--el-border-color-lighter);
  background: var(--el-fill-color-blank);
  color: var(--el-text-color-regular);
  border-radius: 999px;
  padding: 6px 10px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 12px;
}

.legend__item.is-off {
  opacity: 0.5;
}

.legend__dot {
  width: 10px;
  height: 10px;
  border-radius: 999px;
}

.plot {
  position: relative;
  overflow-x: auto;
}

.svg {
  width: 860px;
  max-width: 100%;
  display: block;
}

.grid line {
  stroke: var(--el-border-color);
  stroke-width: 1;
}

.crosshair line {
  stroke: var(--el-border-color);
  stroke-width: 1;
  stroke-dasharray: 4 6;
}

.line {
  fill: none;
  stroke-width: 2.6;
}

.dot {
  stroke: var(--el-bg-color-overlay);
  stroke-width: 1;
}

.xlabels text {
  font-size: 11px;
  fill: var(--el-text-color-secondary);
}

.tooltip {
  position: absolute;
  top: 0;
  left: 0;
  min-width: 200px;
  max-width: 240px;
  padding: 10px 12px;
  border-radius: 14px;
  background: var(--el-bg-color-overlay);
  color: var(--el-text-color-primary);
  border: 1px solid var(--el-border-color-lighter);
  backdrop-filter: blur(10px);
  pointer-events: none;
}

.tooltip__title {
  font-weight: 700;
  font-size: 12px;
  margin-bottom: 8px;
}

.tooltip__rows {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
}

.tooltip__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.tooltip__dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  display: inline-block;
  flex: 0 0 auto;
}

.tooltip__name {
  flex: 1 1 auto;
  opacity: 0.9;
}

.tooltip__value {
  flex: 0 0 auto;
  font-variant-numeric: tabular-nums;
}
</style>
