<script setup lang="ts">
import { ElMessage } from 'element-plus'

import CapacityAccountCard from '@/components/dashboard/CapacityAccountCard.vue'
import CapacityHero from '@/components/dashboard/CapacityHero.vue'
import DramaTrend from '@/components/dashboard/DramaTrend.vue'
import { fetchCapacityOverview, fetchDramaOverview } from '@/api/dashboard'
import { refreshDriveAccountProfiles } from '@/api/extensions'
import { fetchTMDBDetail } from '@/api/media'
import { fetchTasks } from '@/api/tasks'
import type { CapacityOverview, DramaOverview } from '@/types/dashboard'
import type { TMDBDetail } from '@/types/media'
import type { TaskItem } from '@/types/tasks'
import { formatBytes, formatDateTime, formatPercent } from '@/utils/capacity'

const dtfBeijing = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

const dramaDays = ref(30)
const dramaLoading = ref(false)
const dramaRefreshing = ref(false)
const dramaOverview = ref<DramaOverview | null>(null)
const dramaTasks = ref<TaskItem[]>([])
const tmdbDetailsById = reactive<Record<number, TMDBDetail | null | undefined>>({})
const tmdbDetailPromises = reactive<Record<number, Promise<TMDBDetail | null> | undefined>>({})
const trendDialogVisible = ref(false)
const showAllFailures = ref(false)

const capacityLoading = ref(false)
const capacityRefreshing = ref(false)
const capacityOverview = ref<CapacityOverview | null>(null)

const accountGroups = computed(() => {
  const groups = new Map<string, CapacityOverview['accounts']>()
  for (const account of capacityOverview.value?.accounts || []) {
    const key = account.profile?.drive_name || account.drive_type
    const current = groups.get(key) || []
    current.push(account)
    groups.set(key, current)
  }
  return Array.from(groups.entries()).map(([name, accounts]) => ({ name, accounts }))
})

const hasAccounts = computed(() => Boolean(capacityOverview.value?.summary.account_count))
const hasCapacityData = computed(() => Boolean(capacityOverview.value?.summary.capacity_account_count))

function beijingDateStr(d: Date) {
  return dtfBeijing.format(d)
}

function addDays(d: Date, delta: number) {
  const copy = new Date(d)
  copy.setDate(copy.getDate() + delta)
  return copy
}

async function runWithConcurrency<T>(items: T[], limit: number, worker: (item: T) => Promise<void>) {
  const queue = [...items]
  const runners: Promise<void>[] = []
  const runOne = async () => {
    while (queue.length) {
      const it = queue.shift()
      if (it === undefined) return
      await worker(it)
    }
  }
  for (let i = 0; i < Math.max(1, limit); i += 1) {
    runners.push(runOne())
  }
  await Promise.all(runners)
}

async function loadDrama() {
  dramaLoading.value = true
  try {
    const [overviewData, allTasks] = await Promise.all([fetchDramaOverview(dramaDays.value), fetchTasks()])
    dramaOverview.value = overviewData
    dramaTasks.value = allTasks.filter((t) => t.task_type === 'drama')
    await loadTMDBDetails()
  } finally {
    dramaLoading.value = false
  }
}

async function handleRefreshDrama() {
  dramaRefreshing.value = true
  try {
    await loadDrama()
    ElMessage.success('追剧数据已刷新')
  } finally {
    dramaRefreshing.value = false
  }
}

async function loadTMDBDetails() {
  const tasks = dramaTasks.value
  const ids = Array.from(
    new Set(
      tasks
        .filter((t) => String(t.tmdb_media_type || '').toLowerCase() === 'tv')
        .map((t) => Number(t.tmdb_id) || 0)
        .filter((n) => Number.isFinite(n) && n > 0),
    ),
  )
  if (!ids.length) return
  await runWithConcurrency(ids, 4, async (id) => {
    if (tmdbDetailsById[id] !== undefined) return
    if (!tmdbDetailPromises[id]) {
      tmdbDetailPromises[id] = fetchTMDBDetail('tv', id)
        .then((data) => data)
        .catch(() => null)
    }
    const detail = await tmdbDetailPromises[id]
    tmdbDetailsById[id] = detail
  })
}

const contentSummary = computed(() => {
  const tasks = dramaTasks.value
  const today = new Date()
  const todayStr = beijingDateStr(today)
  const next7Str = beijingDateStr(addDays(today, 7))

  let withNextAirDateCount = 0
  let todayCount = 0
  let next7dCount = 0

  for (const task of tasks) {
    const tmdbId = Number(task.tmdb_id) || 0
    if (!tmdbId) continue
    const detail = tmdbDetailsById[tmdbId] || null
    const data: any = detail?.data || null
    const airDate = String(data?.next_episode_to_air?.air_date || '').trim()
    if (!airDate) continue
    withNextAirDateCount += 1
    if (airDate === todayStr) todayCount += 1
    if (airDate >= todayStr && airDate <= next7Str) next7dCount += 1
  }

  return {
    with_next_air_date_count: withNextAirDateCount,
    today_count: todayCount,
    next7d_count: next7dCount,
  }
})

const activeTaskCount = computed(() => dramaTasks.value.filter((t) => t.enabled).length)

function titleFromTask(task: TaskItem) {
  const tmdbId = Number(task.tmdb_id) || 0
  const detail = tmdbId ? tmdbDetailsById[tmdbId] || null : null
  const data: any = detail?.data || null
  return String(data?.name || data?.title || '').trim() || String(task.taskname || '').trim() || `任务 #${task.id}`
}

function episodeLabelFromDetail(data: any, kind: 'last' | 'next') {
  const source = kind === 'next' ? data?.next_episode_to_air : data?.last_episode_to_air
  const season = Number(source?.season_number) || 0
  const ep = Number(source?.episode_number) || 0
  if (season > 0 && ep > 0) return `S${String(season).padStart(2, '0')}E${String(ep).padStart(2, '0')}`
  return ''
}

function timeAgoFromIso(iso?: string | null) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const diff = Date.now() - d.getTime()
  const s = Math.max(0, Math.floor(diff / 1000))
  if (s < 60) return `${s}秒前`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}分钟前`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}小时前`
  const day = Math.floor(h / 24)
  return `${day}天前`
}

function relativeDayLabel(isoDate: string) {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const d = new Date(`${isoDate}T00:00:00`)
  if (Number.isNaN(d.getTime())) return isoDate
  const diff = Math.round((d.getTime() - today.getTime()) / (1000 * 60 * 60 * 24))
  if (diff === 0) return '今天'
  if (diff === 1) return '明天'
  if (diff === 2) return '后天'
  if (diff > 2) return `${diff}天后`
  return isoDate
}

const taskSuccessRate = computed(() => {
  if (!dramaOverview.value) return null
  const s = dramaOverview.value.summary
  if (!s) return 1
  const success = Number(s.execution_success) || 0
  const failed = Number(s.execution_failed) || 0
  const total = success + failed
  if (!total) return 1
  return success / total
})

const updateProgressSummary = computed(() => {
  const tasks = dramaTasks.value.filter((t) => t.tmdb_id && String(t.tmdb_media_type || '').toLowerCase() === 'tv')
  const linked = tasks.length
  let latest = 0
  let behind = 0
  let unknown = 0
  let behindTotal = 0
  let behindMax = 0
  for (const task of tasks) {
    const p = task.drama_update_progress
    if (!p || !p.available) {
      unknown += 1
      continue
    }
    if (p.is_latest) {
      latest += 1
      continue
    }
    const n = typeof p.behind_episodes === 'number' ? p.behind_episodes : null
    if (n === null) {
      unknown += 1
      continue
    }
    if (n <= 0) {
      latest += 1
      continue
    }
    behind += 1
    behindTotal += n
    behindMax = Math.max(behindMax, n)
  }
  const ratio = linked > 0 ? latest / linked : null
  const avgBehind = behind > 0 ? behindTotal / behind : null
  return { linked, latest, behind, unknown, ratio, avgBehind, behindMax }
})

const updateProgressText = computed(() => {
  const r = updateProgressSummary.value.ratio
  if (r === null) return '--'
  return formatPercent(r)
})

const successRateText = computed(() => {
  const v = taskSuccessRate.value
  if (v === null || v === undefined || Number.isNaN(v)) {
    if (dramaTasks.value.length) return '100%'
    return '--'
  }
  return formatPercent(v)
})

const monthSuccessCount = computed(() => dramaOverview.value?.summary.monthly_success_count || 0)

const capacitySpaceText = computed(() => {
  const s = capacityOverview.value?.summary
  if (!s) return '--'
  const used = formatBytes(s.total_used_space)
  const total = formatBytes(s.total_space)
  if (used === '--' || total === '--') return '--'
  return `${used} / ${total}`
})

const recentSuccesses = computed(() => {
  const items: Array<{
    task: TaskItem
    started_at: string
    adapter_snapshot: Record<string, any>
  }> = []
  for (const task of dramaTasks.value) {
    for (const ex of task.executions || []) {
      if (String(ex.status || '').toLowerCase() !== 'success') continue
      items.push({ task, started_at: String(ex.started_at), adapter_snapshot: ex.adapter_snapshot || {} })
    }
  }
  items.sort((a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime())
  return items.slice(0, 2)
})

const upcomingAiring = computed(() => {
  const today = beijingDateStr(new Date())
  const maxDate = beijingDateStr(addDays(new Date(), 7))
  const items: Array<{
    task: TaskItem
    air_date: string
    episode: string
  }> = []

  for (const task of dramaTasks.value) {
    if (!task.enabled) continue
    if (String(task.tmdb_media_type || '').toLowerCase() !== 'tv') continue
    const tmdbId = Number(task.tmdb_id) || 0
    if (!tmdbId) continue
    const detail = tmdbDetailsById[tmdbId] || null
    const data: any = detail?.data || null
    const airDate = String(data?.next_episode_to_air?.air_date || '').trim()
    if (!airDate) continue
    if (airDate < today || airDate > maxDate) continue
    items.push({ task, air_date: airDate, episode: episodeLabelFromDetail(data, 'next') })
  }

  items.sort((a, b) => String(a.air_date).localeCompare(String(b.air_date)))
  return items.slice(0, 2)
})

const failures = computed(() => dramaOverview.value?.recent_failures || [])
const displayFailures = computed(() => failures.value.slice(0, 3))
const hiddenFailures = computed(() => failures.value.slice(3))

const trendPoints = computed(() => dramaOverview.value?.trend || [])

async function loadCapacityOverview() {
  capacityLoading.value = true
  try {
    capacityOverview.value = await fetchCapacityOverview()
  } finally {
    capacityLoading.value = false
  }
}

async function handleRefreshCapacity() {
  capacityRefreshing.value = true
  try {
    await refreshDriveAccountProfiles()
    await loadCapacityOverview()
    ElMessage.success('容量快照已刷新')
  } finally {
    capacityRefreshing.value = false
  }
}

watch(
  () => dramaDays.value,
  () => {
    loadDrama()
  },
)

onMounted(() => {
  loadDrama()
  loadCapacityOverview()
})
</script>

<template>
  <div class="dashboard">
    <div class="section-header">
      <div class="section-header__title">
        <div class="section-header__eyebrow">Dashboard</div>
        <h2>追剧仪表盘</h2>
        <div class="section-header__desc">
          <span>活跃订阅 {{ activeTaskCount }}</span>
          <span class="dot">·</span>
          <span>即将更新 {{ contentSummary.next7d_count }}</span>
          <span class="dot">·</span>
          <span>任务成功率 {{ successRateText }}</span>
          <span class="dot">·</span>
          <span>容量预警 {{ capacityOverview?.warning_accounts.length || 0 }}</span>
        </div>
      </div>
      <div class="toolbar__right">
        <el-radio-group v-model="dramaDays" size="small">
          <el-radio-button :value="7">近7天</el-radio-button>
          <el-radio-button :value="30">近30天</el-radio-button>
        </el-radio-group>
        <el-button type="primary" :loading="dramaRefreshing" @click="handleRefreshDrama">刷新追剧数据</el-button>
      </div>
    </div>

    <section class="metric-strip dashboard-metrics" v-loading="dramaLoading">
      <div class="glass-panel metric-tile">
        <div class="metric-tile__label">活跃订阅</div>
        <div class="metric-tile__value">{{ activeTaskCount }}</div>
        <div class="metric-tile__hint">
          <span v-if="dramaOverview?.summary.unknown_schedule_count">未配置更新日 {{ dramaOverview.summary.unknown_schedule_count }}</span>
          <span v-else>更新日配置完整</span>
        </div>
      </div>
      <div class="glass-panel metric-tile">
        <div class="metric-tile__label">本月新增</div>
        <div class="metric-tile__value">{{ monthSuccessCount }}</div>
        <div class="metric-tile__hint">本月成功执行次数</div>
      </div>
      <div class="glass-panel metric-tile">
        <div class="metric-tile__label">网盘空间使用率</div>
        <div class="metric-tile__value">{{ capacityOverview ? formatPercent(capacityOverview.summary.usage_ratio) : '--' }}</div>
        <div class="metric-tile__hint">
          <span v-if="capacityOverview">
            {{ capacitySpaceText }} · 预警 {{ capacityOverview.warning_accounts.length }}
          </span>
          <span v-else>汇总已用 / 总容量</span>
        </div>
      </div>
      <div class="glass-panel metric-tile">
        <div class="metric-tile__label">任务成功率</div>
        <div class="metric-tile__value">{{ successRateText }}</div>
        <div class="metric-tile__hint">
          <span v-if="dramaOverview">
            成功 {{ dramaOverview.summary.execution_success }} · 失败 {{ dramaOverview.summary.execution_failed }}
          </span>
          <span v-else>暂无执行记录</span>
        </div>
      </div>
      <div class="glass-panel metric-tile">
        <div class="metric-tile__label">最新剧集比例</div>
        <div class="metric-tile__value">{{ updateProgressText }}</div>
        <div class="metric-tile__hint">
          <span v-if="updateProgressSummary.linked">
            最新 {{ updateProgressSummary.latest }} · 落后 {{ updateProgressSummary.behind }} · 未知 {{ updateProgressSummary.unknown }}
          </span>
          <span v-else>仅统计已关联 TMDB 的任务</span>
        </div>
      </div>
    </section>

    <div class="updates-row">
      <section class="glass-panel updates-card" v-loading="dramaLoading">
        <div class="section-header">
          <div class="section-header__title">
            <div class="section-header__eyebrow">Updates</div>
            <h2>最近更新</h2>
            <div class="section-header__desc">
              <span>调度 {{ dramaOverview?.scheduler.enabled ? '已开启' : '未开启' }}</span>
              <span class="dot">·</span>
              <span>封禁 {{ dramaOverview?.summary.banned_count || 0 }}</span>
              <span class="dot">·</span>
              <span>失败 {{ dramaOverview?.summary.execution_failed || 0 }}</span>
            </div>
          </div>
          <div class="toolbar__right">
            <router-link to="/tasks/drama">
              <el-button>追剧任务</el-button>
            </router-link>
            <router-link to="/tasks/calendar">
              <el-button>追剧日历</el-button>
            </router-link>
            <el-button @click="trendDialogVisible = true">任务趋势</el-button>
          </div>
        </div>

        <el-empty v-if="!recentSuccesses.length" description="暂无成功记录，手动运行一次任务后再查看。" :image-size="88" />
        <div v-else class="update-list">
          <div v-for="item in recentSuccesses" :key="`${item.task.id}-${item.started_at}`" class="update-row">
            <div class="update-row__main">
              <div class="update-row__title">
                <span class="update-row__icon">📺</span>
                <span class="update-row__name">{{ titleFromTask(item.task) }}</span>
              </div>
              <div class="update-row__desc">
                <span>{{ timeAgoFromIso(item.started_at) }}</span>
                <span class="meta-dot">·</span>
                <span>{{ String(item.adapter_snapshot?.drive_type || item.task.account_name || '自动') }}网盘</span>
                <span class="meta-dot">·</span>
                <el-tag size="small" type="success">成功</el-tag>
              </div>
            </div>
          </div>
        </div>

        <div v-if="failures.length" class="failures-card">
          <div class="failures-card__head">
            <div class="failures-card__title">近期失败</div>
            <div class="failures-card__right">
              <span class="status-pill status-pill--danger">{{ failures.length }} 条</span>
              <el-button size="small" text @click="showAllFailures = !showAllFailures">
                {{ showAllFailures ? '收起' : '展开' }}
              </el-button>
            </div>
          </div>
          <div class="failures-list">
            <div v-for="f in displayFailures" :key="`${f.task_id}-${f.started_at}`" class="failure-row">
              <div class="failure-row__main">
                <div class="failure-row__title">{{ f.taskname }}</div>
                <div class="failure-row__desc">
                  <span>{{ formatDateTime(f.started_at) }}</span>
                  <span v-if="f.stage" class="meta-dot">·</span>
                  <span v-if="f.stage">阶段 {{ f.stage }}</span>
                </div>
                <div v-if="f.message" class="failure-row__msg">{{ f.message }}</div>
              </div>
              <router-link to="/tasks/drama">
                <el-button size="small">查看</el-button>
              </router-link>
            </div>

            <el-collapse-transition>
              <div v-if="showAllFailures && hiddenFailures.length" class="failures-list">
                <div v-for="f in hiddenFailures" :key="`${f.task_id}-${f.started_at}`" class="failure-row">
                  <div class="failure-row__main">
                    <div class="failure-row__title">{{ f.taskname }}</div>
                    <div class="failure-row__desc">
                      <span>{{ formatDateTime(f.started_at) }}</span>
                      <span v-if="f.stage" class="meta-dot">·</span>
                      <span v-if="f.stage">阶段 {{ f.stage }}</span>
                    </div>
                    <div v-if="f.message" class="failure-row__msg">{{ f.message }}</div>
                  </div>
                  <router-link to="/tasks/drama">
                    <el-button size="small">查看</el-button>
                  </router-link>
                </div>
              </div>
            </el-collapse-transition>
          </div>
        </div>
      </section>

      <section class="glass-panel upcoming-card" v-loading="dramaLoading">
        <div class="section-header">
          <div class="section-header__title">
            <div class="section-header__eyebrow">Upcoming</div>
            <h2>即将播出</h2>
            <div class="section-header__desc">
              <span>{{ upcomingAiring.length ? `未来 7 天 ${upcomingAiring.length} 部` : '未来 7 天暂无' }}</span>
            </div>
          </div>
        </div>

        <el-empty v-if="!upcomingAiring.length" description="未来 7 天暂无已识别的更新日。" :image-size="88" />
        <div v-else class="upcoming-list">
          <div v-for="it in upcomingAiring" :key="`${it.task.id}-${it.air_date}`" class="upcoming-row">
            <div class="upcoming-row__left">
              <span class="update-row__icon">🗓️</span>
              <span class="upcoming-row__name">{{ titleFromTask(it.task) }}</span>
              <span v-if="it.episode" class="meta-dot">·</span>
              <span v-if="it.episode">{{ it.episode }}</span>
            </div>
            <div class="upcoming-row__right">{{ relativeDayLabel(it.air_date) }}</div>
          </div>
        </div>
      </section>
    </div>

    <el-dialog v-model="trendDialogVisible" title="任务趋势（成功数 / 失败数 / 成功率）" width="920">
      <DramaTrend :points="trendPoints" />
    </el-dialog>

    <section class="glass-panel capacity-section">
      <div class="capacity-title">
        <div class="capacity-title__left">
          <div class="section-header__eyebrow">Capacity</div>
          <div class="capacity-title__name">容量管理</div>
        </div>
        <div class="capacity-title__right">
          <span class="status-pill" :class="capacityOverview?.warning_accounts.length ? 'status-pill--danger' : 'status-pill--success'">
            预警 {{ capacityOverview?.warning_accounts.length || 0 }}
          </span>
          <span class="status-pill">最近刷新 {{ formatDateTime(capacityOverview?.updated_at) }}</span>
          <router-link to="/extensions/drives">
            <el-button size="small">账号管理</el-button>
          </router-link>
          <el-button type="primary" size="small" :loading="capacityRefreshing" @click="handleRefreshCapacity">刷新容量</el-button>
        </div>
      </div>

      <div v-loading="capacityLoading" class="capacity-body">
        <CapacityHero v-if="capacityOverview" :summary="capacityOverview.summary" />

        <section class="glass-panel capacity-overview-card">
          <div class="section-header">
            <div class="section-header__title">
              <div class="section-header__eyebrow">Overview</div>
              <h2>总体占比</h2>
              <div class="section-header__desc">基于所有支持容量统计的账号进行汇总，不支持容量的账号会在下方单独列出。</div>
            </div>
          </div>

          <template v-if="hasCapacityData && capacityOverview">
            <div class="metric-strip" style="margin-top: 18px">
              <div class="glass-panel metric-tile">
                <div class="metric-tile__label">总已用 / 总容量</div>
                <div class="metric-tile__value">{{ formatBytes(capacityOverview.summary.total_used_space) }}</div>
                <div class="metric-tile__hint">/ {{ formatBytes(capacityOverview.summary.total_space) }}</div>
              </div>
              <div class="glass-panel metric-tile">
                <div class="metric-tile__label">总体使用率</div>
                <div class="metric-tile__value">{{ formatPercent(capacityOverview.summary.usage_ratio) }}</div>
                <div class="metric-tile__hint">建议重点关注高于阈值的账号</div>
              </div>
            </div>
            <el-progress
              style="margin-top: 18px"
              :percentage="Math.round((capacityOverview.summary.usage_ratio || 0) * 100)"
              :stroke-width="12"
              :show-text="false"
              :status="(capacityOverview.summary.usage_ratio || 0) >= 0.85 ? 'exception' : 'success'"
            />
          </template>
          <el-empty v-else description="暂无可统计的容量数据，点击“刷新容量”后再查看。" :image-size="88" />
        </section>

        <section v-if="capacityOverview" class="glass-panel dashboard-section">
          <div class="group-stack__title">
            <h3>预警账号</h3>
            <span class="status-pill" :class="capacityOverview.warning_accounts.length ? 'status-pill--danger' : 'status-pill--success'">
              {{ capacityOverview.warning_accounts.length }} 个账号
            </span>
          </div>
          <div v-if="capacityOverview.warning_accounts.length" class="card-grid" style="margin-top: 18px">
            <CapacityAccountCard v-for="item in capacityOverview.warning_accounts" :key="item.id" :account="item" />
          </div>
          <el-empty v-else description="当前没有超过阈值的账号。" :image-size="88" />
        </section>

        <template v-if="hasAccounts">
          <section v-for="group in accountGroups" :key="group.name" class="group-stack">
            <div class="group-stack__title">
              <h3>{{ group.name }}</h3>
              <span class="status-pill">{{ group.accounts.length }} 个账号</span>
            </div>
            <div class="card-grid">
              <CapacityAccountCard v-for="item in group.accounts" :key="item.id" :account="item" />
            </div>
          </section>
        </template>

        <section v-if="capacityOverview?.unsupported_accounts.length" class="glass-panel dashboard-section">
          <div class="group-stack__title">
            <h3>未支持容量的账号</h3>
            <span class="status-pill">{{ capacityOverview.unsupported_accounts.length }} 个账号</span>
          </div>
          <div class="card-grid" style="margin-top: 18px">
            <CapacityAccountCard
              v-for="item in capacityOverview.unsupported_accounts"
              :key="`unsupported-${item.id}`"
              :account="item"
              compact
            />
          </div>
        </section>

        <section v-if="capacityOverview && !hasAccounts" class="glass-panel dashboard-section">
          <div class="empty-copy">当前还没有创建任何网盘账号，请先前往“账号管理”添加账号，再回到此处查看容量总览。</div>
        </section>
      </div>
    </section>
  </div>
</template>

<style scoped>
.dashboard-metrics {
  grid-template-columns: repeat(5, minmax(0, 1fr));
}

.dot,
.meta-dot {
  margin: 0 6px;
  color: var(--el-text-color-secondary);
}

.updates-card {
  padding: 22px;
}

.updates-row {
  display: grid;
  grid-template-columns: 1.55fr 0.85fr;
  gap: 20px;
  align-items: start;
}

.update-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-top: 12px;
}

.update-row {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  padding: 14px;
  border-radius: 18px;
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
}

.update-row__title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 700;
}

.update-row__icon {
  width: 18px;
  display: inline-flex;
  justify-content: center;
}

.update-row__name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 420px;
}

.update-row__desc {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.failures-card {
  margin-top: 14px;
  padding: 14px;
  border-radius: 18px;
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
}

.failures-card__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.failures-card__title {
  font-weight: 700;
}

.failures-card__right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.failures-list {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.failure-row {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  padding: 12px 14px;
  border-radius: 16px;
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
}

.failure-row__title {
  font-weight: 650;
}

.failure-row__desc {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.failure-row__msg {
  margin-top: 6px;
  font-size: 13px;
  color: var(--el-text-color-regular);
  line-height: 1.5;
  word-break: break-word;
}

.upcoming-card {
  padding: 22px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.upcoming-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.upcoming-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 14px;
  padding: 14px;
  border-radius: 18px;
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
}

.upcoming-row__left {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 650;
  overflow: hidden;
}

.upcoming-row__name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 360px;
}

.upcoming-row__right {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}

.capacity-section {
  padding: 12px 16px;
}

.capacity-title {
  width: 100%;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}

.capacity-title__left {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.capacity-title__name {
  font-size: 16px;
  font-weight: 700;
}

.capacity-title__right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.capacity-body {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding: 8px 0 10px;
}

@media (max-width: 1100px) {
  .dashboard-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .updates-row {
    grid-template-columns: 1fr;
  }

  .update-row__name {
    max-width: 260px;
  }

  .upcoming-row__name {
    max-width: 220px;
  }
}
</style>
