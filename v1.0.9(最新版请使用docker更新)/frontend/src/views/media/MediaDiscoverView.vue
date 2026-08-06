<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'

import { fetchDoubanCategories, fetchDoubanList, fetchTMDBDetail, searchTMDB } from '@/api/media'
import DramaTaskDrawer from '@/components/tasks/DramaTaskDrawer.vue'
import { createTask, fetchTasks, updateTask } from '@/api/tasks'
import { fetchSyncTasks } from '@/api/syncTasks'
import { fetchDriveAccounts, fetchPlugins } from '@/api/extensions'
import { TASK_WRITE } from '@/constants/permissions'
import { useAuthStore } from '@/stores/auth'
import { useIsMobile } from '@/composables/useIsMobile'
import type { DriveAccountItem, PluginItem } from '@/types/extensions'
import type { DoubanCategory, DoubanListItem, TMDBBrief } from '@/types/media'
import type { SyncTaskItem } from '@/types/syncTasks'
import type { TaskItem } from '@/types/tasks'

const TMDB_IMAGE_BASE = 'https://image.tmdb.org/t/p/w342'

const auth = useAuthStore()
const canWrite = computed(() => auth.permissions.includes(TASK_WRITE))
const isMobile = useIsMobile()

const categories = ref<DoubanCategory[]>([])
const categoriesLoading = ref(false)

const filters = reactive({
  main: '',
  sub: '',
})

const listState = reactive({
  loading: false,
  start: 0,
  limit: 20,
  total: 0,
  tmdbConfigured: false,
  notice: '' as string | null,
  isMockData: null as boolean | null,
  mockReason: '' as string | null,
})

const items = ref<DoubanListItem[]>([])

const searchState = reactive({
  q: '',
  loading: false,
  configured: false,
  checked: false,
})
const searchItems = ref<TMDBBrief[]>([])
const searchPager = reactive({
  page: 1,
  totalPages: 0,
  totalResults: 0,
  pageSize: 20,
})

const viewMode = ref<'douban' | 'tmdb'>('douban')

const accounts = ref<DriveAccountItem[]>([])
const plugins = ref<PluginItem[]>([])
const tasksCache = ref<TaskItem[]>([])
const tasksLoading = ref(false)
const syncTasks = ref<SyncTaskItem[]>([])
const syncTasksLoading = ref(false)

const runLogDialog = reactive({
  visible: false,
  title: '执行日志',
  content: '',
  status: '',
  stage: '',
  message: '',
  taskId: 0,
})
let runLogController: AbortController | null = null

const taskDrawer = reactive({
  visible: false,
  submitting: false,
  currentTask: null as TaskItem | null,
  presetTaskname: '' as string,
  presetTmdb: null as { tmdb_id: number; tmdb_media_type: 'movie' | 'tv' } | null,
})

const existingTaskDialog = reactive({
  visible: false,
  count: 0,
  target: null as TaskItem | null,
  tmdb: null as { tmdb_id: number; tmdb_media_type: 'movie' | 'tv' } | null,
  presetTaskname: '' as string,
})

const tmdbPick = reactive({
  visible: false,
  loading: false,
  items: [] as TMDBBrief[],
  selectedId: 0,
  mediaType: '' as 'movie' | 'tv' | '',
  sourceTitle: '' as string,
  sourceYear: '' as string,
})

const detail = reactive({
  visible: false,
  loading: false,
  mediaType: '' as 'movie' | 'tv' | '',
  tmdbId: 0,
  data: {} as Record<string, any>,
  updateWeekdays: [] as number[],
})

const currentCategory = computed(() => categories.value.find((c) => c.key === filters.main) || null)
const subOptions = computed(() => currentCategory.value?.subs || [])

function posterUrlFromTMDB(path?: string | null) {
  if (!path) return ''
  return `${TMDB_IMAGE_BASE}${path}`
}

function bestDoubanPoster(item: { pic?: { normal?: string | null } | null }) {
  const url = String(item.pic?.normal || '').trim()
  if (!url) return ''
  if (!/^https?:\/\//i.test(url)) return url
  return `/api/media/proxy-image?url=${encodeURIComponent(url)}`
}

function bestTitle(item: TMDBBrief) {
  return item.media_type === 'movie' ? item.title : item.name
}

function candidateTitle(item: any, mediaType: any) {
  const mt = String(mediaType || '').toLowerCase() === 'movie' ? 'movie' : 'tv'
  return mt === 'movie' ? String(item?.title || '') : String(item?.name || '')
}

function normalizeDoubanTitleForTMDBSearch(title: string) {
  const raw = String(title || '').trim()
  if (!raw) return ''
  let out = raw
  out = out.replace(/\s*第\s*[0-9一二三四五六七八九十百千两〇零]+\s*季\s*/g, ' ')
  out = out.replace(/^[\s·\-—_:：]+/g, '')
  out = out.replace(/[\s·\-—_:：]+$/g, '')
  out = out.replace(/\s+/g, ' ').trim()
  return out
}

async function ensureTaskDepsLoaded() {
  if (tasksLoading.value) return
  tasksLoading.value = true
  try {
    const [acc, pls, ts] = await Promise.all([fetchDriveAccounts(), fetchPlugins(), fetchTasks()])
    accounts.value = acc || []
    plugins.value = pls || []
    tasksCache.value = ts || []
  } finally {
    tasksLoading.value = false
  }
}

function pickLatestTask(items: TaskItem[]) {
  return [...items].sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')))[0] || null
}

function findExistingDramaTasks(tmdb_id: number, tmdb_media_type: 'movie' | 'tv') {
  return (tasksCache.value || []).filter((t) => {
    if (!t || t.task_type !== 'drama') return false
    if (Number(t.tmdb_id) !== Number(tmdb_id)) return false
    return String(t.tmdb_media_type || '').toLowerCase() === tmdb_media_type
  })
}

async function openNewDramaTask(presetTaskname: string, tmdb_id: number, tmdb_media_type: 'movie' | 'tv') {
  syncTasksLoading.value = true
  try {
    await fetchSyncTasks()
      .then((data) => { syncTasks.value = data || [] })
      .catch(() => { syncTasks.value = [] })
  } finally {
    syncTasksLoading.value = false
  }
  taskDrawer.currentTask = null
  taskDrawer.presetTaskname = String(presetTaskname || '').trim()
  taskDrawer.presetTmdb = { tmdb_id, tmdb_media_type }
  taskDrawer.visible = true
}

async function openEditDramaTask(task: TaskItem) {
  syncTasksLoading.value = true
  try {
    await fetchSyncTasks()
      .then((data) => { syncTasks.value = data || [] })
      .catch(() => { syncTasks.value = [] })
  } finally {
    syncTasksLoading.value = false
  }
  taskDrawer.currentTask = task
  taskDrawer.presetTaskname = ''
  taskDrawer.presetTmdb = null
  taskDrawer.visible = true
}

function openExistingTaskDialog(target: TaskItem, count: number, tmdb: { tmdb_id: number; tmdb_media_type: 'movie' | 'tv' }, presetTaskname: string) {
  existingTaskDialog.count = Number(count) || 0
  existingTaskDialog.target = target
  existingTaskDialog.tmdb = tmdb
  existingTaskDialog.presetTaskname = String(presetTaskname || '').trim()
  existingTaskDialog.visible = true
}

function closeExistingTaskDialog() {
  existingTaskDialog.visible = false
  existingTaskDialog.count = 0
  existingTaskDialog.target = null
  existingTaskDialog.tmdb = null
  existingTaskDialog.presetTaskname = ''
}

function confirmEditExistingTask() {
  const target = existingTaskDialog.target
  closeExistingTaskDialog()
  if (target) openEditDramaTask(target)
}

function confirmCreateNewTask() {
  const tmdb = existingTaskDialog.tmdb
  const name = existingTaskDialog.presetTaskname
  closeExistingTaskDialog()
  if (tmdb) openNewDramaTask(name, tmdb.tmdb_id, tmdb.tmdb_media_type)
}

async function openTaskWithExistingChoice(tmdb: { tmdb_id: number; tmdb_media_type: 'movie' | 'tv' }, presetTaskname: string) {
  await ensureTaskDepsLoaded()
  const existed = findExistingDramaTasks(tmdb.tmdb_id, tmdb.tmdb_media_type)
  if (existed.length) {
    const target = pickLatestTask(existed)
    if (target) {
      openExistingTaskDialog(target, existed.length, tmdb, presetTaskname)
      return
    }
  }
  openNewDramaTask(presetTaskname, tmdb.tmdb_id, tmdb.tmdb_media_type)
}

async function oneClickAddFromTmdbRow(row: TMDBBrief) {
  const mt = String(row.media_type || '').trim().toLowerCase()
  if (mt !== 'movie' && mt !== 'tv') {
    ElMessage.warning('不支持的媒体类型')
    return
  }
  const tmdbId = Number((row as any).id) || 0
  if (tmdbId <= 0) {
    ElMessage.warning('缺少 TMDB ID')
    return
  }
  await openTaskWithExistingChoice({ tmdb_id: tmdbId, tmdb_media_type: mt as any }, bestTitle(row) || '')
}

async function showTmdbPickForDouban(row: DoubanListItem) {
  if (!listState.tmdbConfigured) {
    ElMessage.warning('未配置 TMDB API Key，无法一键添加任务')
    return
  }
  const title = String(row.title || '').trim()
  const year = String(row.year || '').trim()
  if (!title) {
    ElMessage.warning('缺少标题')
    return
  }
  const searchTitle = normalizeDoubanTitleForTMDBSearch(title) || title
  const mediaType = String(currentCategory.value?.media_type || '').trim().toLowerCase()
  const type = mediaType === 'movie' ? 'movie' : 'tv'

  tmdbPick.visible = true
  tmdbPick.loading = true
  tmdbPick.items = []
  tmdbPick.selectedId = 0
  tmdbPick.mediaType = type as any
  tmdbPick.sourceTitle = title
  tmdbPick.sourceYear = year
  try {
    const data = await searchTMDB({ q: searchTitle, type: type as any, year: year || undefined, page: 1 })
    if (!data.configured) {
      ElMessage.warning('未配置 TMDB API Key')
      tmdbPick.visible = false
      return
    }
    const list = data.items || []
    tmdbPick.items = list
    if (list.length) {
      let picked: TMDBBrief | null = null
      if (year) {
        const key = type === 'movie' ? 'release_date' : 'first_air_date'
        picked = list.find((x) => String((x as any)[key] || '').startsWith(year)) || null
      }
      picked = picked || list[0]
      tmdbPick.selectedId = Number(picked.id) || 0
    }
  } finally {
    tmdbPick.loading = false
  }
}

async function confirmTmdbPick() {
  const id = Number(tmdbPick.selectedId) || 0
  if (id <= 0) return
  const item = (tmdbPick.items || []).find((x) => Number(x.id) === id) || null
  if (!item) return
  const mt = tmdbPick.mediaType
  if (mt !== 'movie' && mt !== 'tv') return
  tmdbPick.visible = false
  await openTaskWithExistingChoice({ tmdb_id: id, tmdb_media_type: mt }, candidateTitle(item, mt) || '')
}

async function handleTaskSave(payload: any) {
  if (taskDrawer.submitting) return
  taskDrawer.submitting = true
  try {
    if (taskDrawer.currentTask?.id) {
      await updateTask(taskDrawer.currentTask.id, payload)
      ElMessage.success('任务已更新')
    } else {
      await createTask(payload)
      ElMessage.success('任务已创建')
    }
    taskDrawer.visible = false
    taskDrawer.currentTask = null
    taskDrawer.presetTaskname = ''
    taskDrawer.presetTmdb = null
    tasksCache.value = await fetchTasks()
  } finally {
    taskDrawer.submitting = false
  }
}

function stopRunLogStream() {
  if (!runLogController) return
  runLogController.abort()
  runLogController = null
}

async function handleRunOnce(payload: any) {
  runLogDialog.visible = true
  runLogDialog.title = `运行一次：${String(payload?.taskname || '').trim() || '未命名任务'}`
  runLogDialog.content = ''
  runLogDialog.status = ''
  runLogDialog.stage = ''
  runLogDialog.message = ''
  runLogDialog.taskId = 0
  runLogController = new AbortController()

  function parseSseBlock(block: string) {
    const lines = block.split('\n')
    let eventType = ''
    const dataLines: string[] = []
    for (const line of lines) {
      if (line.startsWith('event:')) eventType = line.slice(6).trim()
      if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
    }
    return { eventType, dataStr: dataLines.join('\n') }
  }

  try {
    const headers: Record<string, string> = {}
    if (auth.accessToken) headers.Authorization = `Bearer ${auth.accessToken}`
    headers['Content-Type'] = 'application/json'
    const response = await fetch('/api/tasks/run/stream', {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
      signal: runLogController.signal,
    })
    if (!response.ok) {
      const text = await response.text().catch(() => '')
      runLogDialog.status = 'failed'
      runLogDialog.message = text || `HTTP ${response.status}`
      ElMessage.error(runLogDialog.message || '任务执行失败')
      return
    }
    const reader = response.body?.getReader()
    if (!reader) {
      runLogDialog.status = 'failed'
      runLogDialog.message = '响应不支持流式读取'
      ElMessage.error(runLogDialog.message)
      return
    }
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
      const parts = buffer.split('\n\n')
      buffer = parts.pop() || ''
      for (const part of parts) {
        if (!part.trim()) continue
        const parsed = parseSseBlock(part)
        if (!parsed.eventType) continue
        let data: any = null
        try {
          data = parsed.dataStr ? JSON.parse(parsed.dataStr) : null
        } catch {
          data = null
        }
        if (parsed.eventType === 'init') {
          runLogDialog.status = 'running'
          continue
        }
        if (parsed.eventType === 'stage') {
          runLogDialog.stage = String(data?.stage || '')
          continue
        }
        if (parsed.eventType === 'log') {
          const line = String(data?.line ?? '')
          runLogDialog.content = runLogDialog.content
            ? runLogDialog.content + '\n' + line
            : line
          continue
        }
        if (parsed.eventType === 'done') {
          runLogDialog.status = String(data?.status || '')
          runLogDialog.message = String(data?.message || '')
          if (!runLogDialog.stage) {
            const s = String(data?.execution?.stage || '')
            if (s) runLogDialog.stage = s
          }
          if (!String(runLogDialog.content || '').trim()) {
            const full = String(data?.execution?.run_log || '')
            if (full) runLogDialog.content = full
          }
          const stageTip =
            runLogDialog.stage && !String(runLogDialog.message || '').includes('阶段=')
              ? `（阶段：${runLogDialog.stage}）`
              : ''
          if (runLogDialog.status === 'success') {
            ElMessage.success('任务已执行')
          } else if (runLogDialog.status === 'skipped') {
            ElMessage.info(`${runLogDialog.message || '任务已跳过'}${stageTip}`)
          } else {
            ElMessage.error(`${runLogDialog.message || '任务执行失败'}${stageTip}`)
          }
          return
        }
      }
    }
  } catch (e: any) {
    if (e?.name === 'AbortError') {
      return
    }
    runLogDialog.status = 'failed'
    runLogDialog.message = String(e?.message || e || '未知错误')
    ElMessage.error(runLogDialog.message || '任务执行失败')
  }
}

async function loadCategories() {
  categoriesLoading.value = true
  try {
    const data = await fetchDoubanCategories()
    categories.value = data.categories || []
    if (!filters.main && categories.value.length) {
      filters.main = categories.value[0].key
      filters.sub = String(categories.value[0].subs?.[0]?.key || '')
    }
  } finally {
    categoriesLoading.value = false
  }
}

async function loadDoubanList() {
  if (!filters.main) return
  listState.loading = true
  try {
    const data = await fetchDoubanList({
      main_category: filters.main,
      sub_category: filters.sub,
      start: listState.start,
      limit: listState.limit,
    })
    items.value = data.items || []
    listState.total = Number(data.total) || 0
    listState.tmdbConfigured = Boolean(data.tmdb_configured)
    listState.notice = data.notice ?? null
    listState.isMockData = data.is_mock_data ?? null
    listState.mockReason = data.mock_reason ?? null
  } finally {
    listState.loading = false
  }
}

function onCategoryChange() {
  const subs = subOptions.value
  const has = subs.some((s) => s.key === filters.sub)
  if (!has) filters.sub = String(subs[0]?.key || '')
  listState.start = 0
  viewMode.value = 'douban'
  loadDoubanList()
}

function onPageChange(page: number) {
  listState.start = (page - 1) * listState.limit
  viewMode.value = 'douban'
  loadDoubanList()
}

const currentPage = computed(() => Math.floor(listState.start / listState.limit) + 1)

async function openDetailByBrief(brief: TMDBBrief) {
  const mt = String(brief.media_type || '').trim().toLowerCase()
  if (mt !== 'movie' && mt !== 'tv') {
    ElMessage.warning('不支持的媒体类型')
    return
  }
  if (!brief.id) {
    ElMessage.warning('缺少 TMDB ID')
    return
  }
  detail.visible = true
  detail.loading = true
  detail.mediaType = mt as any
  detail.tmdbId = brief.id
  detail.data = {}
  detail.updateWeekdays = []
  try {
    const data = await fetchTMDBDetail(mt as any, brief.id)
    detail.data = data.data || {}
    detail.updateWeekdays = Array.isArray((data as any).update_weekdays) ? ((data as any).update_weekdays as any) : []
  } finally {
    detail.loading = false
  }
}

async function openDetailFromDouban(row: DoubanListItem) {
  if (!listState.tmdbConfigured) {
    ElMessage.warning('未配置 TMDB API Key，无法获取 TMDB 详情')
    return
  }

  const mediaType = String(currentCategory.value?.media_type || '').trim().toLowerCase()
  const type = mediaType === 'movie' ? 'movie' : 'tv'
  const title = String(row.title || '').trim()
  const year = String(row.year || '').trim()
  if (!title) {
    ElMessage.warning('缺少标题')
    return
  }
  const searchTitle = normalizeDoubanTitleForTMDBSearch(title) || title

  detail.visible = true
  detail.loading = true
  detail.mediaType = type as any
  detail.tmdbId = 0
  detail.data = {}

  try {
    const data = await searchTMDB({ q: searchTitle, type: type as any, year: year || undefined, page: 1 })
    if (!data.configured) {
      ElMessage.warning('未配置 TMDB API Key')
      return
    }
    const list = data.items || []
    if (!list.length) {
      ElMessage.warning('未匹配到 TMDB 条目')
      return
    }

    let picked: TMDBBrief | null = null
    if (year) {
      const key = type === 'movie' ? 'release_date' : 'first_air_date'
      picked = list.find((x) => String((x as any)[key] || '').startsWith(year)) || null
    }
    picked = picked || list[0]
    await openDetailByBrief(picked)
  } finally {
    detail.loading = false
  }
}

async function runSearch(page: number) {
  const q = String(searchState.q || '').trim()
  if (!q) return
  searchState.loading = true
  try {
    const data = await searchTMDB({ q, type: 'multi', page })
    searchState.configured = Boolean(data.configured)
    searchState.checked = true
    searchPager.page = Number(data.page) || page
    searchPager.totalPages = Number(data.total_pages) || 0
    searchPager.totalResults = Number(data.total_results) || 0
    searchItems.value = data.items || []
    if (!searchState.configured) {
      ElMessage.warning('未配置 TMDB API Key')
    }
  } catch (e: any) {
    searchState.checked = true
    ElMessage.error(e?.message || '搜索失败')
  } finally {
    searchState.loading = false
  }
}

async function doSearch() {
  const q = String(searchState.q || '').trim()
  if (!q) {
    viewMode.value = 'douban'
    searchItems.value = []
    searchPager.page = 1
    searchPager.totalPages = 0
    searchPager.totalResults = 0
    searchState.checked = false
    return
  }
  searchPager.page = 1
  await runSearch(1)
  viewMode.value = 'tmdb'
}

async function onSearchPageChange(page: number) {
  searchPager.page = page
  viewMode.value = 'tmdb'
  await runSearch(page)
}

const isTmdbMode = computed(() => viewMode.value === 'tmdb')

const detailTitle = computed(() => {
  const d = detail.data || {}
  if (detail.mediaType === 'movie') return String(d.title || d.original_title || '详情')
  if (detail.mediaType === 'tv') return String(d.name || d.original_name || '详情')
  return '详情'
})

const detailPoster = computed(() => posterUrlFromTMDB(detail.data?.poster_path))

const tvSeasons = computed(() => {
  const seasons = (detail.data as any)?.seasons
  if (!Array.isArray(seasons)) return []
  return seasons.filter((s: any) => typeof s === 'object' && s && Number(s.season_number) > 0)
})

const tvTotalEpisodes = computed(() => {
  const n = (detail.data as any)?.number_of_episodes
  if (typeof n === 'number') return n
  const sum = tvSeasons.value.reduce((acc: number, s: any) => acc + (Number(s.episode_count) || 0), 0)
  return sum || null
})

const tvLastEpisodeToAir = computed(() => {
  const last = (detail.data as any)?.last_episode_to_air
  if (!last || typeof last !== 'object') return null
  const seasonNumber = Number(last.season_number) || 0
  const episodeNumber = Number(last.episode_number) || 0
  if (seasonNumber <= 0 || episodeNumber <= 0) return null
  return {
    season_number: seasonNumber,
    episode_number: episodeNumber,
    name: String(last.name || ''),
    air_date: String(last.air_date || ''),
  }
})

const tvAiredEpisodes = computed(() => {
  const total = tvTotalEpisodes.value
  const status = String((detail.data as any)?.status || '').toLowerCase()
  if (status === 'ended' && typeof total === 'number' && total > 0) return total

  const last = tvLastEpisodeToAir.value
  if (!last) return null

  const prev = tvSeasons.value
    .filter((s: any) => Number(s.season_number) > 0 && Number(s.season_number) < last.season_number)
    .reduce((acc: number, s: any) => acc + (Number(s.episode_count) || 0), 0)
  const aired = prev + last.episode_number
  return aired > 0 ? aired : null
})

const tvProgressText = computed(() => {
  if (detail.mediaType !== 'tv') return ''
  const aired = tvAiredEpisodes.value
  const total = tvTotalEpisodes.value
  if (aired != null && total != null) return `已播：${aired}/${total}`
  if (aired != null) return `已播：${aired}`
  if (total != null) return `总集数：${total}`
  return ''
})

const tvUpdateText = computed(() => {
  if (detail.mediaType !== 'tv') return ''
  const days = Array.isArray(detail.updateWeekdays) ? detail.updateWeekdays : []
  const uniq = Array.from(new Set(days.map((x) => Number(x)).filter((x) => x >= 1 && x <= 7)))
  uniq.sort((a, b) => a - b)
  if (!uniq.length) return ''
  const map: Record<number, string> = { 1: '一', 2: '二', 3: '三', 4: '四', 5: '五', 6: '六', 7: '日' }
  const label = uniq.map((x) => map[x] || String(x)).join('、')
  return `周${label}更新`
})

onMounted(async () => {
  await loadCategories()
  await loadDoubanList()
})
</script>

<template>
  <div class="page">
    <div class="page__header">
      <div class="page__title">影视发现</div>
    </div>

    <el-card class="page__card search-card" shadow="never">
      <el-input v-model="searchState.q" class="search-card__input" placeholder="搜索 TMDB 资源（点击搜索后切换结果）" clearable @keyup.enter="doSearch">
        <template #prefix>
          <el-icon class="search-card__icon"><Search /></el-icon>
        </template>
        <template #append>
          <el-button type="primary" :loading="searchState.loading" @click="doSearch">搜索</el-button>
        </template>
      </el-input>
      <div class="search-card__hint" v-if="searchState.checked && !searchState.configured">未配置 TMDB：无法搜索。</div>
    </el-card>

    <template v-if="isTmdbMode">
      <el-card class="page__card" shadow="never">
        <div v-loading="searchState.loading" class="poster-grid">
          <div v-for="row in searchItems" :key="String(row.id || row.title || row.name)" class="poster-card" @click="openDetailByBrief(row)">
            <div class="poster-card__cover">
              <el-image v-if="posterUrlFromTMDB(row.poster_path)" :src="posterUrlFromTMDB(row.poster_path)" fit="cover" class="poster-card__img" />
              <div v-else class="poster-card__placeholder">暂无海报</div>
              <div class="poster-card__rating">
                {{ row.vote_average != null ? Number(row.vote_average).toFixed(1) : '-' }}
              </div>
            </div>
            <div class="poster-card__meta">
              <div class="poster-card__title" :title="bestTitle(row) || ''">{{ bestTitle(row) || '-' }}</div>
              <div class="poster-card__sub">
                {{ row.media_type === 'movie' ? row.release_date || '' : row.first_air_date || '' }}
              </div>
            </div>
            <div class="poster-card__actions" v-if="canWrite">
              <el-button size="small" type="primary" text :disabled="!searchState.configured" @click.stop="oneClickAddFromTmdbRow(row)">
                一键添加任务
              </el-button>
            </div>
          </div>
        </div>
        <div class="pager" v-if="searchPager.totalResults > 0">
          <el-pagination
            background
            layout="prev, pager, next"
            :current-page="searchPager.page"
            :page-size="searchPager.pageSize"
            :total="searchPager.totalResults"
            :disabled="searchState.loading"
            @current-change="onSearchPageChange"
          />
        </div>
      </el-card>
    </template>

    <template v-else>
      <div class="page__hint">
        <div v-if="listState.notice">{{ listState.notice }}</div>
        <div v-if="listState.isMockData">当前为模拟数据：{{ listState.mockReason || '豆瓣接口不可用' }}</div>
      </div>

      <el-card class="page__card page__card--compact" shadow="never">
        <template #header>
          <div class="toolbar">
            <div class="toolbar__title">筛选</div>
            <div class="toolbar__content">
              <el-select v-model="filters.main" size="small" :disabled="categoriesLoading" style="width: 220px" @change="onCategoryChange">
                <el-option v-for="c in categories" :key="c.key" :label="c.label" :value="c.key" />
              </el-select>
              <el-select v-model="filters.sub" size="small" :disabled="categoriesLoading" style="width: 220px" @change="onCategoryChange">
                <el-option v-for="s in subOptions" :key="s.key" :label="s.label" :value="s.key" />
              </el-select>
            </div>
          </div>
        </template>
        <div v-loading="listState.loading" class="poster-grid">
          <div v-for="row in items" :key="row.id" class="poster-card" @click="openDetailFromDouban(row)">
            <div class="poster-card__cover">
              <el-image v-if="bestDoubanPoster(row)" :src="bestDoubanPoster(row)" fit="cover" class="poster-card__img" />
              <div v-else class="poster-card__placeholder">暂无海报</div>
              <div class="poster-card__rating">
                {{ row.rating?.value != null ? Number(row.rating.value).toFixed(1) : '-' }}
              </div>
            </div>
            <div class="poster-card__meta">
              <div class="poster-card__title" :title="row.title">{{ row.title }}</div>
              <div class="poster-card__sub">{{ row.card_subtitle || '' }}</div>
            </div>
            <div class="poster-card__actions" v-if="canWrite">
              <el-button size="small" type="primary" text :disabled="!listState.tmdbConfigured" @click.stop="showTmdbPickForDouban(row)">
                一键添加任务
              </el-button>
            </div>
          </div>
        </div>

        <div class="pager">
          <el-pagination
            background
            layout="prev, pager, next"
            :current-page="currentPage"
            :page-size="listState.limit"
            :total="listState.total"
            @current-change="onPageChange"
          />
        </div>
      </el-card>
    </template>

    <el-drawer v-model="detail.visible" :title="detailTitle" :size="isMobile ? '100%' : '520px'">
      <div v-loading="detail.loading" class="detail">
        <div class="detail__top">
          <el-image v-if="detailPoster" :src="detailPoster" fit="cover" class="detail__poster" />
          <div class="detail__meta">
            <div class="detail__name">{{ detailTitle }}</div>
            <div class="detail__sub">
              <span v-if="detail.mediaType === 'movie'">{{ detail.data.release_date }}</span>
              <span v-else-if="detail.mediaType === 'tv'">{{ detail.data.first_air_date }}</span>
              <span v-if="detail.data.vote_average != null"> · {{ Number(detail.data.vote_average).toFixed(1) }}</span>
            </div>
            <div class="detail__sub" v-if="detail.data.genres?.length">
              {{ detail.data.genres.map((g: any) => g.name).filter(Boolean).join(' / ') }}
            </div>
            <div class="detail__sub" v-if="detail.mediaType === 'tv' && (detail.data.number_of_seasons != null || tvTotalEpisodes != null)">
              <span v-if="detail.data.number_of_seasons != null">季数：{{ detail.data.number_of_seasons }}</span>
              <span v-if="tvTotalEpisodes != null"> · 总集数：{{ tvTotalEpisodes }}</span>
            </div>
            <div class="detail__sub" v-if="detail.mediaType === 'tv' && tvProgressText">
              {{ tvProgressText }}
              <span v-if="tvLastEpisodeToAir">
                · 当前到 S{{ tvLastEpisodeToAir.season_number }}E{{ tvLastEpisodeToAir.episode_number }}
              </span>
            </div>
            <div class="detail__sub" v-if="detail.mediaType === 'tv' && tvUpdateText">
              {{ tvUpdateText }}
            </div>
          </div>
        </div>
        <div class="detail__overview" v-if="detail.data.overview">
          {{ detail.data.overview }}
        </div>
        <div v-if="detail.mediaType === 'tv' && tvSeasons.length" class="detail__seasons">
          <div class="detail__section-title">季信息</div>
          <el-table :data="tvSeasons" size="small" style="width: 100%">
            <el-table-column prop="season_number" label="季" width="60" />
            <el-table-column prop="name" label="名称" min-width="140" show-overflow-tooltip />
            <el-table-column prop="episode_count" label="集数" width="70" />
            <el-table-column prop="air_date" label="首播" width="110" />
          </el-table>
        </div>
      </div>
    </el-drawer>

    <el-dialog
      v-model="existingTaskDialog.visible"
      title="已存在追剧任务"
      width="560px"
      :close-on-click-modal="false"
      @close="closeExistingTaskDialog"
    >
      <div style="font-size: 14px; line-height: 1.6">
        <div>检测到该影视已存在 <span style="font-weight: 600">{{ existingTaskDialog.count }}</span> 个关联的追剧任务。</div>
        <div style="margin-top: 10px; padding: 10px 12px; border-radius: 12px; background: var(--el-fill-color-blank); border: 1px solid var(--el-border-color-lighter)">
          <div style="font-weight: 600">{{ existingTaskDialog.target?.taskname || '' }}</div>
          <div style="margin-top: 4px; font-size: 12px; color: var(--el-text-color-secondary)">
            最近更新：{{ existingTaskDialog.target?.updated_at || '-' }}
          </div>
        </div>
        <div style="margin-top: 10px; color: var(--el-text-color-secondary); font-size: 13px">
          你可以选择修改已有任务，或者继续添加一个新的追剧任务。
        </div>
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 10px">
          <el-button @click="closeExistingTaskDialog">取消</el-button>
          <el-button @click="confirmCreateNewTask">添加新任务</el-button>
          <el-button type="primary" @click="confirmEditExistingTask">修改已有任务</el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="tmdbPick.visible"
      title="选择 TMDB 条目"
      width="720px"
      class="tmdb-pick-dialog"
    >
      <div v-loading="tmdbPick.loading">
        <el-table
          :data="tmdbPick.items"
          style="width: 100%"
          class="tmdb-pick-table"
          highlight-current-row
          row-key="id"
          @current-change="(row) => (tmdbPick.selectedId = Number(row?.id) || 0)"
        >
          <el-table-column label="海报" width="90">
            <template #default="{ row }">
              <el-image v-if="posterUrlFromTMDB(row.poster_path)" :src="posterUrlFromTMDB(row.poster_path)" fit="cover" style="width: 60px; height: 84px; border-radius: 6px" />
            </template>
          </el-table-column>
          <el-table-column label="标题" min-width="220">
            <template #default="{ row }">
              <div class="title">
                <div class="title__main">{{ candidateTitle(row, tmdbPick.mediaType) }}</div>
                <div class="title__sub">{{ tmdbPick.mediaType === 'movie' ? row.release_date : row.first_air_date }}</div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="评分" :width="isMobile ? 70 : 90">
            <template #default="{ row }">{{ row.vote_average != null ? Number(row.vote_average).toFixed(1) : '-' }}</template>
          </el-table-column>
          <el-table-column v-if="!isMobile" label="简介" min-width="260" show-overflow-tooltip>
            <template #default="{ row }">{{ row.overview || '' }}</template>
          </el-table-column>
        </el-table>
        <div v-if="!tmdbPick.items.length" class="page__hint">未找到候选条目，可取消后改用顶部 TMDB 搜索。</div>
      </div>
      <template #footer>
        <el-button @click="tmdbPick.visible = false">取消</el-button>
        <el-button type="primary" :disabled="!tmdbPick.selectedId" @click="confirmTmdbPick">确定</el-button>
      </template>
    </el-dialog>

    <DramaTaskDrawer
      v-model="taskDrawer.visible"
      :task="taskDrawer.currentTask"
      :accounts="accounts"
      :plugins="plugins"
      :sync-tasks="syncTasks"
      :submitting="taskDrawer.submitting"
      :preset-taskname="taskDrawer.presetTaskname"
      :preset-tmdb="taskDrawer.presetTmdb"
      :auto-deep-suggest="!taskDrawer.currentTask"
      @save="handleTaskSave"
      @run-once="handleRunOnce"
    />

    <el-dialog
      v-model="runLogDialog.visible"
      :title="runLogDialog.title"
      :width="isMobile ? '92vw' : '720px'"
      :close-on-click-modal="runLogDialog.status !== 'running'"
      :close-on-press-escape="runLogDialog.status !== 'running'"
      :show-close="runLogDialog.status !== 'running'"
      @closed="stopRunLogStream"
    >
      <div v-if="runLogDialog.status === 'running'" style="color: var(--el-color-primary); margin-bottom: 8px">执行中...</div>
      <div v-if="runLogDialog.stage" style="color: var(--el-color-info); margin-bottom: 8px">阶段：{{ runLogDialog.stage }}</div>
      <pre v-if="runLogDialog.content" style="white-space: pre-wrap; font-size: 12px; line-height: 1.5; background: var(--el-fill-color-blank); border: 1px solid var(--el-border-color-lighter); border-radius: 4px; padding: 12px; max-height: 480px; overflow: auto; color: var(--el-text-color-primary)">{{ runLogDialog.content }}</pre>
      <template #footer>
        <el-button @click="runLogDialog.visible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page {
  padding: 12px;
}
.page__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.page__title {
  font-size: 18px;
  font-weight: 600;
}
.page__hint {
  margin: 10px 0 14px;
  color: var(--el-text-color-regular);
  font-size: 13px;
  line-height: 1.7;
}
.page__hint--compact {
  margin: 8px 0 0;
}
.page__card {
  margin-bottom: 10px;
}
.page__card--compact :deep(.el-card__body) {
  padding: 10px 12px;
}
.page__card--compact :deep(.el-card__header) {
  padding: 10px 12px;
}
.search-card :deep(.el-card__body) {
  padding: 10px 12px;
}
.search-card__input :deep(.el-input__wrapper) {
  border-radius: 12px;
}
.search-card__icon {
  color: var(--el-text-color-secondary);
}
.search-card__hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.toolbar__title {
  font-weight: 600;
  white-space: nowrap;
}
.toolbar__content {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  flex: 1;
}
.card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.filters {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}
.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
.poster-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 12px;
  min-height: 120px;
}
.poster-card {
  background: var(--el-fill-color-blank);
  border-radius: 12px;
  border: 1px solid var(--el-border-color-lighter);
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  cursor: pointer;
  transition: transform 0.12s ease, box-shadow 0.12s ease, border-color 0.12s ease;
  height: 100%;
}
.poster-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.08);
  border-color: rgba(148, 163, 184, 0.4);
}
.poster-card__cover {
  position: relative;
  border-radius: 10px;
  overflow: hidden;
  aspect-ratio: 2 / 3;
  background: var(--el-fill-color-light);
}
.poster-card__img {
  width: 100%;
  height: 100%;
}
.poster-card__placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.poster-card__rating {
  position: absolute;
  top: 8px;
  right: 8px;
  background: rgba(15, 23, 42, 0.78);
  color: #fff;
  font-size: 12px;
  padding: 2px 6px;
  border-radius: 10px;
}
.poster-card__meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.poster-card__title {
  font-weight: 600;
  font-size: 14px;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 40px;
}
.poster-card__sub {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 34px;
}
.poster-card__actions {
  display: flex;
  justify-content: flex-start;
  margin-top: auto;
}
.title__main {
  font-weight: 600;
}
.title__sub {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-top: 4px;
}

:deep(.tmdb-pick-dialog .el-table) {
  --el-table-text-color: var(--el-text-color-primary);
  --el-table-border-color: var(--el-border-color-lighter);
  --el-table-header-text-color: var(--el-text-color-secondary);
}

:deep(.tmdb-pick-dialog .el-table__body td.el-table__cell) {
  color: var(--el-text-color-primary);
}

:deep(.tmdb-pick-dialog .el-table__body tr.current-row > td.el-table__cell) {
  background: var(--el-table-current-row-bg-color) !important;
}

:deep(.tmdb-pick-dialog .el-table__body tr.current-row:hover > td.el-table__cell) {
  background: var(--el-table-current-row-bg-color) !important;
}
.detail {
  padding: 4px 4px 18px;
}
.detail__top {
  display: flex;
  gap: 14px;
}
.detail__poster {
  width: 140px;
  height: 196px;
  border-radius: 8px;
  overflow: hidden;
  flex: none;
}
.detail__meta {
  flex: 1;
}
.detail__name {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 6px;
}
.detail__sub {
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}
.detail__overview {
  margin-top: 14px;
  white-space: pre-wrap;
  line-height: 1.7;
}
.detail__seasons {
  margin-top: 14px;
}
.detail__section-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
}

@media (max-width: 767px) {
  .detail {
    padding: 0 0 18px;
  }

  .detail__top {
    flex-direction: column;
  }

  .detail__poster {
    width: 120px;
    height: 168px;
  }
}
</style>
