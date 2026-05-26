<script setup lang="ts">
import { ElMessageBox } from 'element-plus'

import { fetchTMDBDetail, searchTMDB } from '@/api/media'
import { browseDrive, fetchMagicRegex, fetchTasks, previewShare, previewShareBatch } from '@/api/tasks'
import { fetchTMDBConfig } from '@/api/tmdb'
import { fetchTaskSuggestions } from '@/api/resourceSearch'
import type { DriveAccountItem, PluginItem } from '@/types/extensions'
import type { TMDBBrief } from '@/types/media'
import type { TaskSuggestionItem } from '@/types/resourceSearch'
import type { DriveBrowseItem, MagicRegexRule, SharePreviewItem, TaskItem } from '@/types/tasks'
import { detectDriveTypeByUrl } from '@/utils/driveType'

const TMDB_IMAGE_BASE = 'https://image.tmdb.org/t/p/w185'

type TaskSuggestionItemExt = TaskSuggestionItem & {
  pdir_fid?: string | null
  latest_video?: any | null
  max_video?: boolean
}

type TaskFormPayload = {
  task_type: string
  taskname: string
  shareurl: string
  savepath: string
  pattern?: string | null
  replace?: string | null
  enddate?: string | null
  ignore_extension: boolean
  sort_index?: number | null
  startfid?: string | null
  account_name?: string | null
  update_subdir?: string | null
  tmdb_id?: number | null
  tmdb_media_type?: string | null
  enabled: boolean
  addition: Record<string, any>
  extra: Record<string, any>
}

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    task?: TaskItem | null
    accounts: DriveAccountItem[]
    plugins: PluginItem[]
    submitting?: boolean
    presetTaskname?: string
    presetTmdb?: { tmdb_id: number; tmdb_media_type: 'movie' | 'tv' } | null
    autoDeepSuggest?: boolean
  }>(),
  {
    task: null,
    submitting: false,
    presetTaskname: '',
    presetTmdb: null,
    autoDeepSuggest: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  save: [payload: TaskFormPayload]
  'run-once': [payload: TaskFormPayload]
}>()

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value ?? {}))
}

const isEditing = computed(() => Boolean(props.task?.id))

const state = reactive({
  taskname: '',
  shareurl: '',
  savepath: '',
  account_choice: '__AUTO__' as string,
  enabled: true,
  pattern: '' as string | null,
  replace: '' as string | null,
  ignore_extension: false,
  sort_index: null as number | null,
  startfid: '' as string | null,
  update_subdir: '' as string | null,
  enddate: '' as string | null,
  tmdb_id: null as number | null,
  tmdb_media_type: null as string | null,
  runweek_mode: 'manual' as 'auto' | 'manual',
  runweek: [] as number[],
  update_subdir_resave_mode: 'none',
  addition: {} as Record<string, any>,
  extra: {} as Record<string, any>,
})

const manualRunweekBackup = ref([] as number[])
const autoRunweekDays = ref([] as number[])

const taskSuggestions = reactive({
  visible: false,
  loading: false,
  verifying: false,
  deep: 0 as 0 | 1,
  runId: 0,
  items: [] as TaskSuggestionItemExt[],
  hideTimer: null as any,
  searchTimer: null as any,
  focused: false,
  notice: '' as string,
  lastQuery: '' as string,
  lastDeep: 0 as 0 | 1,
})

const tmdbLink = reactive({
  visible: false,
  loading: false,
  configured: true,
  type: 'tv' as 'movie' | 'tv',
  q: '' as string,
  year: '' as string,
  items: [] as TMDBBrief[],
  selectedId: 0,
  detailsById: {} as Record<number, any>,
  loadingById: {} as Record<number, boolean>,
})

const activeAccounts = computed(() => {
  return props.accounts.filter((item) => Boolean(item.enabled) && item.runtime_status === 'active')
})

const unavailableSelectedAccount = computed(() => {
  if (state.account_choice === '__AUTO__') return null
  const name = String(state.account_choice || '').trim()
  if (!name) return null
  if (activeAccounts.value.some((item) => item.name === name)) return null
  return props.accounts.find((item) => item.name === name) || { name, drive_type: '', enabled: false, runtime_status: null }
})

const unavailableSelectedAccountLabel = computed(() => {
  const item: any = unavailableSelectedAccount.value
  if (!item) return ''
  const driveType = item.drive_type ? `（${item.drive_type}）` : ''
  const status = item.enabled ? '不可用' : '已禁用'
  const rt = item.runtime_status ? String(item.runtime_status) : ''
  const suffix = rt ? `${status}/${rt}` : status
  return `${item.name}${driveType}（${suffix}）`
})

const magicRegex = reactive({
  loading: false,
  selectedKey: '' as string,
  rules: [] as MagicRegexRule[],
})

const activeMagicRule = computed(() => {
  const key = String(state.pattern || '').trim()
  if (!key) return null
  return magicRegex.rules.find((r) => r.key === key) || null
})

const drivePicker = reactive({
  visible: false,
  loading: false,
  dirPath: '',
  pdir_fid: '' as string,
  drive_type: '' as string,
  paths: [] as Array<{ fid: string; name: string }>,
  items: [] as DriveBrowseItem[],
  sortBy: 'file_name' as 'file_name' | 'updated_at',
  sortOrder: 'asc' as 'asc' | 'desc',
  mobileSort: 'file_name:asc' as string,
})

const sharePicker = reactive({
  visible: false,
  loading: false,
  shareurl: '' as string,
  root_shareurl: '' as string,
  pdir_fid: null as string | null,
  stack: [] as Array<{ name: string; pdir_fid: string }>,
  items: [] as SharePreviewItem[],
})

const startfidPicker = reactive({
  visible: false,
  loading: false,
  items: [] as SharePreviewItem[],
})

const shareAuto = reactive({
  timer: null as any,
  runId: 0,
  lastResolved: '' as string,
})

const autoFill = reactive({
  loading: false,
  text: '正在自动填写...',
  runId: 0,
})

const saveAuto = reactive({
  timer: null as any,
  applying: false,
  touched: false,
  lastApplied: '' as string,
  tasksLoading: false,
  tasks: null as TaskItem[] | null,
  tmdbDetailCache: {} as Record<string, any>,
})

const viewport = reactive({ width: window.innerWidth })
const isMobile = computed(() => viewport.width <= 768)
const shareDialogWidth = computed(() => (isMobile.value ? '96vw' : '1100px'))

function onResize() {
  viewport.width = window.innerWidth
}

onMounted(() => {
  window.addEventListener('resize', onResize, { passive: true })
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
})

function formatTs(value: any) {
  if (value === undefined || value === null || value === '') return ''
  const n = Number(value)
  const ts = Number.isFinite(n) ? (n < 1e12 ? n * 1000 : n) : Date.parse(String(value))
  if (!Number.isFinite(ts)) return String(value)
  const d = new Date(ts)
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${d.getFullYear()}-${mm}-${dd} ${hh}:${mi}`
}

function formatSize(size: any) {
  const n = Number(size)
  if (!Number.isFinite(n) || n < 0) return ''
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = n
  let idx = 0
  while (value >= 1024 && idx < units.length - 1) {
    value /= 1024
    idx += 1
  }
  if (idx === 0) return `${Math.floor(value)} ${units[idx]}`
  return `${value.toFixed(value >= 10 ? 1 : 2)} ${units[idx]}`
}

function sanitizeSuggestionQuery(value: string) {
  return String(value || '')
    .replace(/\((19|20)\d{2}\)/g, '')
    .trim()
}

function showSuggestions() {
  if (taskSuggestions.hideTimer) {
    clearTimeout(taskSuggestions.hideTimer)
    taskSuggestions.hideTimer = null
  }
  taskSuggestions.focused = true
  taskSuggestions.visible = true
}

function hideSuggestionsLater() {
  if (taskSuggestions.hideTimer) clearTimeout(taskSuggestions.hideTimer)
  taskSuggestions.focused = false
  taskSuggestions.hideTimer = setTimeout(() => {
    taskSuggestions.visible = false
  }, 180)
}

function resetSuggestions() {
  taskSuggestions.runId += 1
  taskSuggestions.visible = false
  taskSuggestions.loading = false
  taskSuggestions.verifying = false
  taskSuggestions.items = []
  taskSuggestions.focused = false
  taskSuggestions.notice = ''
  taskSuggestions.lastQuery = ''
  taskSuggestions.lastDeep = 0
  if (taskSuggestions.hideTimer) {
    clearTimeout(taskSuggestions.hideTimer)
    taskSuggestions.hideTimer = null
  }
  if (taskSuggestions.searchTimer) {
    clearTimeout(taskSuggestions.searchTimer)
    taskSuggestions.searchTimer = null
  }
}

function tmdbBindLabel() {
  const id = Number(state.tmdb_id) || 0
  const mt = String(state.tmdb_media_type || '').toLowerCase()
  if (id > 0 && (mt === 'movie' || mt === 'tv')) return `${mt} #${id}`
  return ''
}

function normalizeWeekdays(value: any) {
  const arr = Array.isArray(value) ? value : []
  const days = arr.map((x) => Number(x)).filter((x) => x >= 1 && x <= 7)
  return Array.from(new Set(days)).sort((a, b) => a - b)
}

async function applyRunweekFromTmdbUpdateWeekdays(tmdbId: number, mediaType: 'movie' | 'tv') {
  if (!props.modelValue) return
  if (!tmdbLink.configured) return
  if (mediaType !== 'tv') return
  const id = Number(tmdbId) || 0
  if (id <= 0) return
  try {
    const res: any = await fetchTMDBDetail('tv', id)
    const days = normalizeWeekdays(res?.episode_weekdays || res?.update_weekdays)
    autoRunweekDays.value = days
  } catch {
    return
  }
}

function posterUrlFromTMDB(path?: string | null) {
  const p = String(path || '').trim()
  if (!p) return ''
  return `${TMDB_IMAGE_BASE}${p}`
}

async function ensureTmdbLinkDetail(id: number) {
  const tmdbId = Number(id) || 0
  if (tmdbId <= 0) return
  if (tmdbLink.detailsById[tmdbId]) return
  if (tmdbLink.loadingById[tmdbId]) return
  tmdbLink.loadingById[tmdbId] = true
  try {
    const data = await fetchTMDBDetail(tmdbLink.type, tmdbId)
    tmdbLink.detailsById[tmdbId] = data.data || {}
  } finally {
    tmdbLink.loadingById[tmdbId] = false
  }
}

function tvTotalEpisodesFromDetail(detail: any) {
  const n = detail?.number_of_episodes
  if (typeof n === 'number' && n > 0) return n
  const seasons = Array.isArray(detail?.seasons) ? detail.seasons : []
  const sum = seasons
    .filter((s: any) => s && typeof s === 'object' && Number(s.season_number) > 0)
    .reduce((acc: number, s: any) => acc + (Number(s.episode_count) || 0), 0)
  return sum > 0 ? sum : null
}

function tvAiredEpisodesFromDetail(detail: any, total: number | null) {
  const status = String(detail?.status || '').toLowerCase()
  if (status === 'ended' && typeof total === 'number' && total > 0) return total
  const last = detail?.last_episode_to_air
  if (!last || typeof last !== 'object') return null
  const seasonNumber = Number(last.season_number) || 0
  const episodeNumber = Number(last.episode_number) || 0
  if (seasonNumber <= 0 || episodeNumber <= 0) return null

  const seasons = Array.isArray(detail?.seasons) ? detail.seasons : []
  const prev = seasons
    .filter((s: any) => s && typeof s === 'object' && Number(s.season_number) > 0 && Number(s.season_number) < seasonNumber)
    .reduce((acc: number, s: any) => acc + (Number(s.episode_count) || 0), 0)
  const aired = prev + episodeNumber
  return aired > 0 ? aired : null
}

function tvProgressTextFromDetail(detail: any) {
  const seasons = typeof detail?.number_of_seasons === 'number' ? detail.number_of_seasons : null
  const total = tvTotalEpisodesFromDetail(detail)
  const aired = tvAiredEpisodesFromDetail(detail, total)
  const last = detail?.last_episode_to_air
  const lastSeason = Number(last?.season_number) || 0
  const lastEp = Number(last?.episode_number) || 0

  const parts: string[] = []
  if (seasons != null) parts.push(`季数：${seasons}`)
  if (total != null) parts.push(`总集数：${total}`)
  if (aired != null && total != null) parts.push(`已播：${aired}/${total}`)
  else if (aired != null) parts.push(`已播：${aired}`)
  if (lastSeason > 0 && lastEp > 0) parts.push(`当前到 S${lastSeason}E${lastEp}`)
  return parts.join(' · ')
}

function tmdbLinkRowProgress(row: any) {
  if (tmdbLink.type !== 'tv') return ''
  const id = Number(row?.id) || 0
  if (id <= 0) return ''
  const detail = tmdbLink.detailsById[id]
  if (detail) return tvProgressTextFromDetail(detail)
  if (tmdbLink.loadingById[id]) return '进度：加载中'
  return ''
}

async function openTmdbLinkDialog() {
  tmdbLink.visible = true
  tmdbLink.loading = false
  tmdbLink.configured = true
  tmdbLink.items = []
  tmdbLink.selectedId = 0
  tmdbLink.detailsById = {}
  tmdbLink.loadingById = {}
  const mt = String(state.tmdb_media_type || '').toLowerCase()
  tmdbLink.type = mt === 'movie' ? 'movie' : 'tv'
  tmdbLink.q = sanitizeSuggestionQuery(state.taskname)
  tmdbLink.year = ''
  if (tmdbLink.q.trim()) {
    await runTmdbLinkSearch()
  }
}

async function runTmdbLinkSearch() {
  const q = String(tmdbLink.q || '').trim()
  if (q.length < 1) return
  tmdbLink.loading = true
  try {
    const data = await searchTMDB({ q, type: tmdbLink.type, year: tmdbLink.year.trim() || undefined, page: 1 })
    tmdbLink.configured = Boolean(data.configured)
    if (!tmdbLink.configured) {
      ElMessage.warning('未配置 TMDB API Key')
      tmdbLink.items = []
      tmdbLink.selectedId = 0
      return
    }
    const list = data.items || []
    tmdbLink.items = list
    tmdbLink.detailsById = {}
    tmdbLink.loadingById = {}
    let picked: TMDBBrief | null = null
    const year = tmdbLink.year.trim()
    if (year) {
      const key = tmdbLink.type === 'movie' ? 'release_date' : 'first_air_date'
      picked = list.find((x: any) => String(x?.[key] || '').startsWith(year)) || null
    }
    picked = picked || list[0] || null
    tmdbLink.selectedId = Number(picked?.id) || 0
    const prefetch = list.slice(0, 6).map((x) => Number((x as any)?.id) || 0).filter((x) => x > 0)
    for (const id of prefetch) {
      ensureTmdbLinkDetail(id)
    }
  } catch (e: any) {
    ElMessage.error(e?.message || 'TMDB 搜索失败')
  } finally {
    tmdbLink.loading = false
  }
}

async function confirmTmdbLink() {
  const id = Number(tmdbLink.selectedId) || 0
  if (id <= 0) return
  state.tmdb_id = id
  state.tmdb_media_type = tmdbLink.type
  if (tmdbLink.type === 'tv' && tmdbLink.configured) {
    if (state.runweek_mode !== 'auto') manualRunweekBackup.value = clone(state.runweek || [])
    state.runweek_mode = 'auto'
    state.runweek = []
    await applyRunweekFromTmdbUpdateWeekdays(id, 'tv')
  } else {
    state.runweek_mode = 'manual'
    autoRunweekDays.value = []
  }
  tmdbLink.visible = false
}

function clearTmdbLink() {
  state.tmdb_id = null
  state.tmdb_media_type = null
  state.runweek_mode = 'manual'
  autoRunweekDays.value = []
  ElMessage.success('已解除关联')
}

async function verifySuggestions(runId: number, items: TaskSuggestionItemExt[]) {
  taskSuggestions.verifying = true
  const pending = items.filter((x) => x.shareurl && (x.verify === null || x.verify === undefined)).map((x) => x.shareurl)
  const dedup = Array.from(new Set(pending))

  const byDrive = new Map<string, string[]>()
  const unknown: string[] = []
  for (const url of dedup) {
    const dt = detectDriveTypeByUrl(url)
    if (!dt) {
      unknown.push(url)
      continue
    }
    const key = String(dt)
    const list = byDrive.get(key) || []
    list.push(url)
    byDrive.set(key, list)
  }

  const driveGroups = Array.from(byDrive.entries()).map(([drive_type, shareurls]) => ({ drive_type, shareurls }))
  driveGroups.sort((a, b) => a.drive_type.localeCompare(b.drive_type))

  const sleep = async (ms: number) => {
    await new Promise((r) => setTimeout(r, ms))
  }

  const syncLargestVideo = (list: TaskSuggestionItemExt[]) => {
    const sizes = list.map((x) => Number((x as any)?.latest_video?.size) || 0)
    const max = sizes.length ? Math.max(...sizes) : 0
    for (const it of list) {
      const s = Number((it as any)?.latest_video?.size) || 0
      it.max_video = max > 0 && s === max
    }
    list.sort((a, b) => {
      const av = Number((a as any)?.latest_video?.size) || 0
      const bv = Number((b as any)?.latest_video?.size) || 0
      if (av !== bv) return bv - av
      return String(a.taskname || '').localeCompare(String(b.taskname || ''))
    })
  }

  for (const { shareurls } of driveGroups) {
    if (runId !== taskSuggestions.runId) return
    if (!props.modelValue) return
    try {
      const data = await previewShareBatch({ shareurls })
      if (runId !== taskSuggestions.runId) return
      const mapping = new Map((data.items || []).map((it) => [it.shareurl, it]))
      for (const it of items) {
        if (!it.shareurl) continue
        const row = mapping.get(it.shareurl) as any
        if (!row) continue
        it.verify = Boolean(row.ok)
        it.pdir_fid = String(row.pdir_fid || row.resolved_pdir_fid || '') || null
        it.latest_video = row.latest_video || null
      }
      syncLargestVideo(items)
    } catch {
      if (runId !== taskSuggestions.runId) return
      for (const it of items) {
        if (shareurls.includes(it.shareurl)) it.verify = false
      }
    }
    await sleep(120 + Math.floor(Math.random() * 180))
  }

  if (unknown.length) {
    for (const url of unknown) {
      if (runId !== taskSuggestions.runId) return
      if (!props.modelValue) return
      try {
        await previewShare({ shareurl: url, max_items: 1 })
        if (runId !== taskSuggestions.runId) return
        for (const it of items) {
          if (it.shareurl === url) it.verify = true
        }
      } catch {
        if (runId !== taskSuggestions.runId) return
        for (const it of items) {
          if (it.shareurl === url) it.verify = false
        }
      }
    }
  }

  if (runId === taskSuggestions.runId) {
    syncLargestVideo(items)
    taskSuggestions.verifying = false
  }
}

async function searchSuggestions(deep: 0 | 1) {
  if (!props.modelValue) return
  if (deep === 0 && !taskSuggestions.focused) return
  const q = sanitizeSuggestionQuery(state.taskname)
  if (q.length < 2) return
  if (q === taskSuggestions.lastQuery && deep === taskSuggestions.lastDeep && taskSuggestions.items.length) {
    taskSuggestions.visible = true
    return
  }
  taskSuggestions.loading = true
  taskSuggestions.deep = deep
  taskSuggestions.lastQuery = q
  taskSuggestions.lastDeep = deep
  taskSuggestions.notice = ''
  taskSuggestions.runId += 1
  const runId = taskSuggestions.runId
  try {
    let driveType: string | null = null
    if (deep === 1) {
      if (state.account_choice !== '__AUTO__') {
        driveType = driveTypeForAccountName(state.account_choice)
      } else {
        const url = String(state.shareurl || '').trim()
        if (url) {
          const dt = detectDriveTypeByUrl(url)
          driveType = dt ? String(dt) : null
        }
      }
    }
    const data = await fetchTaskSuggestions(q, deep, driveType)
    if (runId !== taskSuggestions.runId) return
    const items = (data.data || []).filter((x) => x && x.shareurl)
    taskSuggestions.notice = String((data as any)?.message || '').trim()
    taskSuggestions.items = items.map((x) => ({ ...x, verify: null }))
    taskSuggestions.visible = true
    if (taskSuggestions.items.length) {
      verifySuggestions(runId, taskSuggestions.items)
    }
  } finally {
    if (runId === taskSuggestions.runId) {
      taskSuggestions.loading = false
    }
  }
}

function scheduleLightSearch() {
  if (!props.modelValue) return
  if (!taskSuggestions.focused) return
  if (taskSuggestions.searchTimer) clearTimeout(taskSuggestions.searchTimer)
  taskSuggestions.searchTimer = setTimeout(() => {
    searchSuggestions(0)
  }, 1000)
}

function selectSuggestion(item: TaskSuggestionItemExt) {
  taskSuggestions.visible = false
  const url = String(item.shareurl || '').trim()
  if (!url) return
  if (shareAuto.timer) clearTimeout(shareAuto.timer)
  shareAuto.runId += 1
  const runId = shareAuto.runId
  shareAuto.lastResolved = url
  state.shareurl = url
  autoFill.runId = runId
  autoFill.loading = true
  autoFill.text = '正在自动定位目录并填写保存路径...'
  previewShareBatch({ shareurls: [url] })
    .then((data) => {
      if (runId !== shareAuto.runId) return
      if (!props.modelValue) return
      const row = (data.items || []).find((x) => String(x.shareurl || '').trim() === url)
      if (!row || !row.ok) return
      const fid = String((row as any).pdir_fid || (row as any).resolved_pdir_fid || '').trim()
      if (fid) {
        const resolved = getShareurl(url, { fid })
        shareAuto.lastResolved = resolved
        state.shareurl = resolved
        state.startfid = null
      } else {
        shareAuto.lastResolved = url
        state.shareurl = url
      }
    })
    .catch(() => {
      return
    })
    .finally(() => {
      if (runId !== shareAuto.runId) return
      if (!props.modelValue) return
      autoFill.text = '正在自动填写保存路径...'
      autoFillSavepath(runId)
        .catch(() => {
          return
        })
        .finally(() => {
          if (runId !== shareAuto.runId) return
          if (!props.modelValue) return
          if (autoFill.runId === runId) autoFill.loading = false
          openSharePicker()
        })
    })
}

function sortUpdatedAt(a: any, b: any) {
  const av = Number(a?.updated_at) || 0
  const bv = Number(b?.updated_at) || 0
  return av - bv
}

function sortDriveList(by = drivePicker.sortBy, order = drivePicker.sortOrder) {
  drivePicker.sortBy = by
  drivePicker.sortOrder = order
  drivePicker.mobileSort = `${drivePicker.sortBy}:${drivePicker.sortOrder}`
  const direction = drivePicker.sortOrder === 'asc' ? 1 : -1
  drivePicker.items.sort((a, b) => {
    if (drivePicker.sortBy === 'updated_at') {
      const av = Number(a.updated_at) || 0
      const bv = Number(b.updated_at) || 0
      return (av - bv) * direction
    }
    const an = String(a.file_name || a.name || '').toLowerCase()
    const bn = String(b.file_name || b.name || '').toLowerCase()
    return an.localeCompare(bn) * direction
  })
}

function applyDriveMobileSort() {
  const [by, order] = String(drivePicker.mobileSort || '').split(':')
  if ((by === 'file_name' || by === 'updated_at') && (order === 'asc' || order === 'desc')) {
    sortDriveList(by, order)
  }
}

function onDriveSortChange(payload: any) {
  const prop = String(payload?.prop || '')
  const order = String(payload?.order || '')
  if (prop !== 'file_name' && prop !== 'updated_at') return
  if (order === 'ascending') sortDriveList(prop as any, 'asc')
  if (order === 'descending') sortDriveList(prop as any, 'desc')
}

function currentDrivePathLabel() {
  if (!drivePicker.paths.length) return '/'
  return `/${drivePicker.paths.map((x) => x.name).join('/')}`
}

async function browseDriveDir(dir_path: string) {
  drivePicker.loading = true
  const account_name = state.account_choice !== '__AUTO__' ? state.account_choice : null
  try {
    const data = await browseDrive({
      dir_path,
      account_name,
      shareurl: state.shareurl || null,
      max_items: 200,
    })
    drivePicker.dirPath = data.dir_path || dir_path
    drivePicker.pdir_fid = data.pdir_fid || (dir_path === '/' || dir_path === '0' ? '0' : drivePicker.pdir_fid)
    drivePicker.drive_type = data.drive_type || ''
    if (Array.isArray(data.paths) && data.paths.length) {
      drivePicker.paths = data.paths
    }
    drivePicker.items = data.exists ? data.items || [] : []
    sortDriveList(drivePicker.sortBy, drivePicker.sortOrder)
  } finally {
    drivePicker.loading = false
  }
}

function extractShareFid(url: string) {
  const m1 = url.match(/#\/list\/share\/([a-zA-Z0-9]{6,64})/)
  if (m1?.[1]) return m1[1]
  const m2 = url.match(/\/([a-fA-F0-9]{32})-?[^/]*$/)
  if (m2?.[1]) return m2[1]
  return null
}

function getShareurl(shareurl: string, dir?: { fid?: string; name?: string }) {
  const fid = String(dir?.fid || '').trim()
  if (!fid || fid === '0') {
    const match = shareurl.match(/.*s\/[a-zA-Z0-9\-_]+(\?[^#]*)?/)
    return (match ? match[0] : shareurl.split('#')[0]).trim()
  }
  if (shareurl.includes(fid)) {
    const m = shareurl.match(new RegExp(`.*/${fid}[^/]*`))
    if (m?.[0]) return m[0]
  }
  if (shareurl.includes('#/list/share')) {
    return `${shareurl.split('#')[0]}#/list/share/${fid}`
  }
  return `${shareurl.split('#')[0]}#/list/share/${fid}`
}

function sortByUpdatedAtDesc(items: SharePreviewItem[]) {
  return [...items].sort((a, b) => {
    const av = Number(a.updated_at) || 0
    const bv = Number(b.updated_at) || 0
    return bv - av
  })
}

function normalizeSavepath(value: string) {
  const s = String(value || '').trim()
  if (!s) return ''
  const normalized = `/${s}`.replace(/\/+/g, '/')
  return normalized.length > 1 ? normalized.replace(/\/+$/, '') : normalized
}

function driveTypeForAccountName(name: string | null | undefined) {
  const n = String(name || '').trim()
  if (!n) return null
  const found = props.accounts.find((x) => String(x.name) === n)
  return found ? String(found.drive_type || '').trim() || null : null
}

function driveTypeForTask(task: TaskItem) {
  const byAccount = driveTypeForAccountName(task.account_name)
  if (byAccount) return byAccount
  const byUrl = detectDriveTypeByUrl(task.shareurl)
  return byUrl ? String(byUrl) : null
}

function currentDriveType() {
  if (state.account_choice !== '__AUTO__') {
    return driveTypeForAccountName(state.account_choice)
  }
  const dt = detectDriveTypeByUrl(state.shareurl)
  return dt ? String(dt) : null
}

function cleanSavepathBase(savepath: string, taskname: string) {
  let p = normalizeSavepath(savepath)
  if (!p) return ''
  p = p.replace(/\/S\d{1,3}$/i, '')
  const name = String(taskname || '').trim()
  if (!name) return p
  const parts = p.split('/').filter(Boolean)
  const last = String(parts.at(-1) || '')
  if (!last) return p
  if (last === name) return normalizeSavepath(parts.slice(0, -1).join('/'))
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  if (new RegExp(`^${escaped}\\s*\\(\\d{4}\\)$`).test(last)) {
    return normalizeSavepath(parts.slice(0, -1).join('/'))
  }
  return p
}

function existingTaskCategory(task: TaskItem) {
  const savepath = normalizeSavepath(task.savepath)
  if (savepath.includes('/动漫')) return '动漫'
  if (savepath.includes('/综艺')) return '综艺'
  const mt = String(task.tmdb_media_type || '').toLowerCase()
  if (mt === 'movie') return '电影'
  if (mt === 'tv') return '电视剧'
  return ''
}

function categoryFromTmdb(mt: string, detail: any) {
  const mediaType = String(mt || '').toLowerCase()
  if (mediaType === 'movie') return '电影'
  const genres = Array.isArray(detail?.genres) ? detail.genres : []
  const ids = new Set<number>()
  const names = new Set<string>()
  for (const g of genres) {
    const id = Number((g as any)?.id)
    if (Number.isFinite(id) && id > 0) ids.add(id)
    const n = String((g as any)?.name || '').trim().toLowerCase()
    if (n) names.add(n)
  }
  const hasAnime = ids.has(16) || Array.from(names).some((n) => n.includes('animation') || n.includes('动画'))
  if (hasAnime) return '动漫'
  const varietyIds = new Set([10764, 10767, 10763])
  const hasVariety = Array.from(varietyIds).some((id) => ids.has(id)) || Array.from(names).some((n) => n.includes('reality') || n.includes('talk') || n.includes('真人秀') || n.includes('脱口秀'))
  if (hasVariety) return '综艺'
  return '电视剧'
}

function ensureCategorySegment(base: string, category: string) {
  const p = normalizeSavepath(base)
  const c = String(category || '').trim()
  if (!p || !c) return p
  const segs = p.split('/').filter(Boolean)
  if (segs.includes(c)) return p
  return normalizeSavepath(`${p}/${c}`)
}

function yearFromTmdbDetail(mt: string, detail: any) {
  const mediaType = String(mt || '').toLowerCase()
  const raw = mediaType === 'movie' ? String(detail?.release_date || '') : String(detail?.first_air_date || '')
  if (raw.length >= 4 && /^\d{4}/.test(raw)) return Number(raw.slice(0, 4))
  return null
}

function appendYearSuffix(name: string, year: number | null) {
  const n = String(name || '').trim()
  if (!n) return ''
  if (!year || !Number.isFinite(year) || year < 1900 || year > 2100) return n
  if (/\(\d{4}\)\s*$/.test(n)) return n
  return `${n}(${year})`
}

async function ensureTasksLoaded() {
  if (saveAuto.tasks) return saveAuto.tasks
  if (saveAuto.tasksLoading) return saveAuto.tasks || []
  saveAuto.tasksLoading = true
  try {
    const data = await fetchTasks()
    saveAuto.tasks = Array.isArray(data) ? data : []
    return saveAuto.tasks
  } catch {
    saveAuto.tasks = []
    return saveAuto.tasks
  } finally {
    saveAuto.tasksLoading = false
  }
}

async function getTmdbDetailForCurrent() {
  const id = Number(state.tmdb_id) || 0
  const mt = String(state.tmdb_media_type || '').toLowerCase()
  if (id <= 0 || (mt !== 'movie' && mt !== 'tv')) return null
  const key = `${mt}:${id}`
  if (saveAuto.tmdbDetailCache[key]) return saveAuto.tmdbDetailCache[key]
  try {
    const res = await fetchTMDBDetail(mt as any, id)
    const detail = (res as any)?.data || null
    saveAuto.tmdbDetailCache[key] = detail
    return detail
  } catch {
    saveAuto.tmdbDetailCache[key] = null
    return null
  }
}

async function autoFillSavepath(runId: number) {
  if (!props.modelValue) return
  if (runId !== shareAuto.runId) return
  if (saveAuto.touched) return
  const currentSave = String(state.savepath || '').trim()
  if (isEditing.value && currentSave && currentSave !== saveAuto.lastApplied) return
  if (currentSave && currentSave !== saveAuto.lastApplied) return

  const dt = currentDriveType()
  if (!dt) return

  const all = await ensureTasksLoaded()
  if (runId !== shareAuto.runId) return

  const candidates = (all || []).filter((t) => driveTypeForTask(t) === dt && String(t.savepath || '').trim())
  if (!candidates.length) return

  const detail = await getTmdbDetailForCurrent()
  if (runId !== shareAuto.runId) return

  const mt = String(state.tmdb_media_type || '').toLowerCase()
  const category = categoryFromTmdb(mt, detail)
  const titleFromTmdb = String(detail?.name || detail?.title || '').trim()
  const baseNameSeg = String(state.taskname || '').trim() || titleFromTmdb
  const year = yearFromTmdbDetail(mt, detail)
  const nameSeg = appendYearSuffix(baseNameSeg, year)
  if (!nameSeg) return

  const seasonCount = Number(detail?.number_of_seasons) || 0
  const needSeason = mt === 'tv' && seasonCount > 1

  const filteredByCat = candidates.filter((t) => existingTaskCategory(t) === category)
  const pool = filteredByCat.length ? filteredByCat : candidates

  const counts = new Map<string, number>()
  const firstIdx = new Map<string, number>()
  for (let i = 0; i < pool.length; i += 1) {
    const t = pool[i]
    const base = cleanSavepathBase(t.savepath, t.taskname)
    if (!base) continue
    counts.set(base, (counts.get(base) || 0) + 1)
    if (!firstIdx.has(base)) firstIdx.set(base, i)
  }
  const sorted = Array.from(counts.entries()).sort((a, b) => {
    if (b[1] !== a[1]) return b[1] - a[1]
    return (firstIdx.get(a[0]) || 0) - (firstIdx.get(b[0]) || 0)
  })
  const baseRoot = sorted[0]?.[0] || ''
  if (!baseRoot) return

  let root = ensureCategorySegment(baseRoot, category)
  root = normalizeSavepath(root)
  let suggested = normalizeSavepath(`${root}/${nameSeg}`)
  if (needSeason) suggested = normalizeSavepath(`${suggested}`)

  saveAuto.applying = true
  try {
    state.savepath = suggested
    saveAuto.lastApplied = suggested
  } finally {
    saveAuto.applying = false
  }
}

function syncState() {
  if (shareAuto.timer) {
    clearTimeout(shareAuto.timer)
    shareAuto.timer = null
  }
  autoFill.loading = false
  shareAuto.lastResolved = ''
  if (props.task) {
    state.taskname = props.task.taskname
    shareAuto.lastResolved = String(props.task.shareurl || '').trim()
    state.shareurl = props.task.shareurl
    state.savepath = props.task.savepath
    state.account_choice = props.task.account_name ? String(props.task.account_name) : '__AUTO__'
    state.enabled = props.task.enabled
    state.pattern = props.task.pattern || null
    state.replace = props.task.replace || null
    state.ignore_extension = props.task.ignore_extension
    state.sort_index = props.task.sort_index ?? null
    state.startfid = props.task.startfid || null
    state.update_subdir = props.task.update_subdir || null
    state.enddate = props.task.enddate || null
    state.tmdb_id = props.task.tmdb_id ?? null
    state.tmdb_media_type = props.task.tmdb_media_type ?? null
    state.addition = clone(props.task.addition || {})
    state.extra = clone(props.task.extra || {})
  } else {
    state.taskname = String(props.presetTaskname || '').trim()
    state.shareurl = ''
    state.savepath = ''
    state.account_choice = '__AUTO__'
    state.enabled = true
    state.pattern = ''
    state.replace = ''
    state.ignore_extension = true
    state.sort_index = 1
    state.startfid = null
    state.update_subdir = null
    state.enddate = null
    state.tmdb_id = props.presetTmdb?.tmdb_id ?? null
    state.tmdb_media_type = props.presetTmdb?.tmdb_media_type ?? null
    state.addition = {}
    state.extra = {}
  }

  saveAuto.touched = false
  saveAuto.lastApplied = ''

  magicRegex.selectedKey = ''

  const runweek = Array.isArray(state.extra.runweek) ? state.extra.runweek : []
  state.runweek = runweek.map((item: any) => Number(item)).filter((item: any) => item >= 1 && item <= 7)
  const mode = String((state.extra as any)?.runweek_mode || '').trim().toLowerCase()
  state.runweek_mode = mode === 'auto' ? 'auto' : 'manual'
  manualRunweekBackup.value = clone(state.runweek || [])
  autoRunweekDays.value = []
  state.update_subdir_resave_mode = String(state.extra.update_subdir_resave_mode || 'none')

  const additionValue: any = state.addition
  if (!additionValue || typeof additionValue !== 'object' || Array.isArray(additionValue)) {
    state.addition = {}
  }
  for (const plugin of props.plugins) {
    const key = plugin.plugin_key
    const defaultCfg = clone(plugin.default_task_config || {})
    const currentCfg: any = (state.addition as any)[key]
    if (!currentCfg || typeof currentCfg !== 'object' || Array.isArray(currentCfg)) {
      ;(state.addition as any)[key] = defaultCfg
      continue
    }
    for (const [k, v] of Object.entries(defaultCfg)) {
      if (!(k in currentCfg)) currentCfg[k] = clone(v)
    }
    for (const field of plugin.task_config_fields || []) {
      const fieldKey = String(field.key || '').trim()
      if (!fieldKey) continue
      if (fieldKey in currentCfg) continue
      if (field.default !== undefined) currentCfg[fieldKey] = clone(field.default)
    }
  }
}

watch(
  () => state.savepath,
  (value) => {
    if (!props.modelValue) return
    if (saveAuto.applying) return
    const s = String(value || '').trim()
    if (!s) {
      saveAuto.touched = false
      saveAuto.lastApplied = ''
      return
    }
    if (s === saveAuto.lastApplied) return
    saveAuto.touched = true
  },
)

watch(
  () => [props.modelValue, props.task, props.plugins] as const,
  async ([visible]) => {
    if (!visible) return
    syncState()
    refreshMagicRegex()
    try {
      const cfg = await fetchTMDBConfig()
      tmdbLink.configured = Boolean(cfg?.has_api_key)
    } catch {
      tmdbLink.configured = false
    }

    if (!tmdbLink.configured && state.runweek_mode === 'auto') {
      state.runweek_mode = 'manual'
    }

    if (!isEditing.value && state.runweek_mode === 'manual') {
      const id = Number(state.tmdb_id) || 0
      const mt = String(state.tmdb_media_type || '').toLowerCase()
      if (tmdbLink.configured && id > 0 && mt === 'tv') {
        state.runweek_mode = 'auto'
      }
    }

    if (state.runweek_mode === 'auto') {
      const id = Number(state.tmdb_id) || 0
      const mt = String(state.tmdb_media_type || '').toLowerCase()
      if (id > 0 && mt === 'tv') {
        applyRunweekFromTmdbUpdateWeekdays(id, 'tv')
      }
    }
    if (props.autoDeepSuggest && !isEditing.value) {
      nextTick(() => {
        searchSuggestions(1)
      })
    }
  },
  { immediate: true, deep: true },
)

function triggerDeepSuggest() {
  searchSuggestions(1)
}

defineExpose({ triggerDeepSuggest })

async function refreshMagicRegex() {
  if (magicRegex.loading) return
  if (magicRegex.rules.length) return
  magicRegex.loading = true
  try {
    const data = await fetchMagicRegex()
    magicRegex.rules = data.rules || []
  } finally {
    magicRegex.loading = false
  }
}

function applyMagicRule(key: string) {
  const rule = magicRegex.rules.find((r) => r.key === key)
  if (!rule) return
  state.pattern = rule.pattern
  state.replace = rule.replace
}

function closeDrawer() {
  resetSuggestions()
  emit('update:modelValue', false)
}

function buildExtraPayload() {
  const extra = clone(state.extra || {})
  extra.runweek_mode = state.runweek_mode
  extra.runweek = state.runweek_mode === 'auto' ? [] : clone(state.runweek || [])
  extra.update_subdir_resave_mode = state.update_subdir_resave_mode
  if ('allow_once' in extra) delete (extra as any).allow_once
  return extra
}

function validateBeforeSubmit() {
  const missing: string[] = []
  if (!String(state.taskname || '').trim()) missing.push('任务名称')
  if (!String(state.shareurl || '').trim()) missing.push('分享链接')
  if (!String(state.savepath || '').trim()) missing.push('保存路径（savepath）')
  if (missing.length) {
    ElMessageBox.alert(`请先填写：${missing.join('、')}`, '提示', {
      type: 'warning',
      confirmButtonText: '知道了',
    })
    return false
  }
  return true
}

function runOnce() {
  if (!validateBeforeSubmit()) return
  const account_name = state.account_choice !== '__AUTO__' ? state.account_choice : null
  const extra = buildExtraPayload()
  extra.allow_once = true
  extra.runweek = []
  emit('run-once', {
    task_type: 'drama',
    taskname: state.taskname.trim(),
    shareurl: state.shareurl.trim(),
    savepath: state.savepath.trim(),
    pattern: state.pattern ? String(state.pattern).trim() : null,
    replace: state.replace ? String(state.replace).trim() : null,
    enddate: state.enddate ? String(state.enddate).trim() : null,
    ignore_extension: Boolean(state.ignore_extension),
    sort_index: state.sort_index ?? null,
    startfid: state.startfid ? String(state.startfid).trim() : null,
    account_name,
    update_subdir: state.update_subdir ? String(state.update_subdir).trim() : null,
    tmdb_id: state.tmdb_id ?? null,
    tmdb_media_type: state.tmdb_media_type ?? null,
    enabled: true,
    addition: clone(state.addition || {}),
    extra,
  })
}

function submit() {
  if (!validateBeforeSubmit()) return
  const account_name = state.account_choice !== '__AUTO__' ? state.account_choice : null
  emit('save', {
    task_type: 'drama',
    taskname: state.taskname.trim(),
    shareurl: state.shareurl.trim(),
    savepath: state.savepath.trim(),
    pattern: state.pattern ? String(state.pattern).trim() : null,
    replace: state.replace ? String(state.replace).trim() : null,
    enddate: state.enddate ? String(state.enddate).trim() : null,
    ignore_extension: Boolean(state.ignore_extension),
    sort_index: state.sort_index ?? null,
    startfid: state.startfid ? String(state.startfid).trim() : null,
    account_name,
    update_subdir: state.update_subdir ? String(state.update_subdir).trim() : null,
    tmdb_id: state.tmdb_id ?? null,
    tmdb_media_type: state.tmdb_media_type ?? null,
    enabled: Boolean(state.enabled),
    addition: clone(state.addition || {}),
    extra: buildExtraPayload(),
  })
}

async function openDrivePicker() {
  drivePicker.visible = true
  drivePicker.sortBy = 'file_name'
  drivePicker.sortOrder = 'asc'
  drivePicker.mobileSort = 'file_name:asc'
  drivePicker.paths = []
  await browseDriveDir(state.savepath || '/')
}

async function refreshDrivePicker() {
  if (drivePicker.pdir_fid) {
    await browseDriveDir(drivePicker.pdir_fid)
    return
  }
  await browseDriveDir(state.savepath || '/')
}

function driveNavigateTo(fid: string, name?: string, opts?: { sliceToIndex?: number }) {
  const targetFid = String(fid || '').trim() || '0'
  if (targetFid === '0' || targetFid === '/') {
    drivePicker.paths = []
    drivePicker.pdir_fid = '0'
    browseDriveDir('/')
    return
  }

  const sliceToIndex = opts?.sliceToIndex
  if (typeof sliceToIndex === 'number' && sliceToIndex >= 0) {
    drivePicker.paths = drivePicker.paths.slice(0, sliceToIndex + 1)
  } else {
    const idx = drivePicker.paths.findIndex((p) => String(p.fid) === targetFid)
    if (idx !== -1) {
      drivePicker.paths = drivePicker.paths.slice(0, idx + 1)
    } else if (name) {
      drivePicker.paths = [...drivePicker.paths, { fid: targetFid, name: String(name) }]
    }
  }
  drivePicker.pdir_fid = targetFid
  browseDriveDir(targetFid)
}

function enterDriveDir(item: DriveBrowseItem) {
  if (!item.is_dir) return
  driveNavigateTo(item.fid, String(item.file_name || item.name || ''))
}

function driveGoRoot() {
  driveNavigateTo('0')
}

function driveGoBack() {
  if (!drivePicker.paths.length) {
    driveGoRoot()
    return
  }
  drivePicker.paths = drivePicker.paths.slice(0, -1)
  const target = drivePicker.paths.at(-1)
  const fid = target?.fid || '0'
  drivePicker.pdir_fid = fid
  browseDriveDir(fid === '0' ? '/' : fid)
}

function useCurrentDrivePath(withTaskname: boolean) {
  const base = currentDrivePathLabel()
  if (withTaskname && state.taskname.trim()) {
    state.savepath = `${base}/${state.taskname.trim()}`.replace(/\/+/g, '/')
  } else {
    state.savepath = base
  }
  drivePicker.visible = false
}

async function openSharePicker() {
  if (!state.shareurl.trim()) {
    ElMessage.warning('请先填写分享链接')
    return
  }
  sharePicker.visible = true
  sharePicker.root_shareurl = getShareurl(state.shareurl.trim(), { fid: '0' })
  sharePicker.shareurl = state.shareurl.trim()
  const fid = extractShareFid(sharePicker.shareurl)
  sharePicker.stack = fid ? [{ name: '当前目录', pdir_fid: fid }] : []
  await refreshSharePicker(null)
}

async function refreshSharePicker(pdir_fid: string | null) {
  sharePicker.loading = true
  try {
    const account_name = state.account_choice !== '__AUTO__' ? state.account_choice : null
    const data = await previewShare({
      shareurl: sharePicker.shareurl,
      account_name,
      pdir_fid: pdir_fid ?? undefined,
      max_items: 200,
      taskname: state.taskname || undefined,
      pattern: state.pattern || undefined,
      replace: state.replace || undefined,
      sort_index: state.sort_index ?? undefined,
      savepath: state.savepath || undefined,
      ignore_extension: state.ignore_extension,
      update_subdir: state.update_subdir || undefined,
      startfid: state.startfid || undefined,
      tmdb_id: state.tmdb_id ?? undefined,
      tmdb_media_type: state.tmdb_media_type || undefined,
    })
    sharePicker.pdir_fid = data.pdir_fid || null
    sharePicker.items = data.items || []
  } finally {
    sharePicker.loading = false
  }
}

function enterShareDir(item: SharePreviewItem) {
  if (!item.is_dir) return
  sharePicker.stack.push({ name: item.name, pdir_fid: item.fid })
  sharePicker.shareurl = getShareurl(sharePicker.root_shareurl, { fid: item.fid, name: item.name })
  refreshSharePicker(item.fid)
}

function goShareBack() {
  sharePicker.stack.pop()
  const target = sharePicker.stack.at(-1)
  const fid = target?.pdir_fid || '0'
  sharePicker.shareurl = getShareurl(sharePicker.root_shareurl, { fid, name: target?.name || '/' })
  refreshSharePicker(fid === '0' ? null : fid)
}

function onShareRowClick(row: SharePreviewItem) {
  if (!row.is_dir) return
  enterShareDir(row)
}

function pickShareFolderCurrent() {
  const current = sharePicker.stack.at(-1)
  if (current?.pdir_fid && current?.name !== '当前目录') {
    state.shareurl = getShareurl(sharePicker.root_shareurl, { fid: current.pdir_fid, name: current.name })
    state.startfid = null
    sharePicker.visible = false
    ElMessage.success('已选择分享文件夹')
    return
  }
  const fid = extractShareFid(sharePicker.shareurl)
  if (fid) {
    state.shareurl = sharePicker.shareurl
    state.startfid = null
    sharePicker.visible = false
    ElMessage.success('已选择分享文件夹')
    return
  }
  ElMessage.warning('请先进入某个文件夹后再选择')
}

async function openStartfidPicker() {
  if (!state.shareurl.trim()) {
    ElMessage.warning('请先填写分享链接')
    return
  }
  startfidPicker.visible = true
  startfidPicker.loading = true
  try {
    const account_name = state.account_choice !== '__AUTO__' ? state.account_choice : null
    const data = await previewShare({
      shareurl: state.shareurl.trim(),
      account_name,
      max_items: 500,
      taskname: state.taskname || undefined,
      pattern: state.pattern || undefined,
      replace: state.replace || undefined,
      sort_index: state.sort_index ?? undefined,
      savepath: state.savepath || undefined,
      ignore_extension: state.ignore_extension,
      update_subdir: state.update_subdir || undefined,
      startfid: null,
      tmdb_id: state.tmdb_id ?? undefined,
      tmdb_media_type: state.tmdb_media_type || undefined,
    })
    startfidPicker.items = sortByUpdatedAtDesc(data.items || []).filter((item) => !item.is_dir)
  } finally {
    startfidPicker.loading = false
  }
}

function selectStartfid(row: SharePreviewItem) {
  if (row.is_dir) return
  state.startfid = row.fid
  startfidPicker.visible = false
  ElMessage.success('已选择起始文件')
}

const weekOptions = [
  { label: '一', value: 1 },
  { label: '二', value: 2 },
  { label: '三', value: 3 },
  { label: '四', value: 4 },
  { label: '五', value: 5 },
  { label: '六', value: 6 },
  { label: '日', value: 7 },
]

const autoRunweekText = computed(() => {
  const days = autoRunweekDays.value || []
  if (!days.length) return ''
  const map = new Map(weekOptions.map((x) => [x.value, x.label] as const))
  return days.map((d) => `周${map.get(Number(d) as any) || d}`).join('、')
})

const autoRunweekDisabled = computed(() => {
  if (!tmdbLink.configured) return true
  const mt = String(state.tmdb_media_type || '').toLowerCase()
  const id = Number(state.tmdb_id) || 0
  return mt !== 'tv' || id <= 0
})

watch(
  () => state.runweek_mode,
  (mode) => {
    if (!props.modelValue) return
    if (mode === 'auto') {
      manualRunweekBackup.value = clone(state.runweek || [])
      state.runweek = []
      const id = Number(state.tmdb_id) || 0
      const mt = String(state.tmdb_media_type || '').toLowerCase()
      if (id > 0 && mt === 'tv') applyRunweekFromTmdbUpdateWeekdays(id, 'tv')
      return
    }
    autoRunweekDays.value = []
    if (!state.runweek.length && manualRunweekBackup.value.length) {
      state.runweek = clone(manualRunweekBackup.value)
    }
  },
)

watch(
  () => [state.tmdb_id, state.tmdb_media_type, state.runweek_mode, tmdbLink.configured] as const,
  ([idRaw, mtRaw, mode, configured]) => {
    if (!props.modelValue) return
    if (mode !== 'auto') return
    if (!configured) return
    const id = Number(idRaw) || 0
    const mt = String(mtRaw || '').toLowerCase()
    if (id > 0 && mt === 'tv') applyRunweekFromTmdbUpdateWeekdays(id, 'tv')
  },
)

async function autoResolveShareFolder(shareurl: string, runId: number) {
  const input = String(shareurl || '').trim()
  if (!input) return
  if (!props.modelValue) return
  if (runId !== shareAuto.runId) return

  const account_name = state.account_choice !== '__AUTO__' ? state.account_choice : null
  const root = getShareurl(input, { fid: '0' })
  let current = input
  let lastItems: SharePreviewItem[] = []
  let sawVideo = false

  const toTs = (v: any) => {
    const n = Number(v)
    if (Number.isFinite(n)) return n < 1e12 ? n * 1000 : n
    const t = Date.parse(String(v || ''))
    return Number.isFinite(t) ? t : 0
  }

  const isVideoFile = (name: any) => {
    const s = String(name || '').toLowerCase()
    return /\.(mp4|mkv|mov|m4v|avi|mpeg|ts|flv|wmv|webm)$/.test(s)
  }

  for (let depth = 0; depth < 12; depth += 1) {
    if (!props.modelValue) return
    if (runId !== shareAuto.runId) return
    const data = await previewShare({ shareurl: current, account_name, max_items: 50 })
    if (!props.modelValue) return
    if (runId !== shareAuto.runId) return
    const items = (Array.isArray(data.items) ? data.items : []) as SharePreviewItem[]
    lastItems = items

    const files = items.filter((x) => x && !x.is_dir)
    const dirs = items.filter((x) => x && x.is_dir)
    if (files.some((f) => isVideoFile(f.name || f.file_name))) {
      sawVideo = true
      break
    }

    if (dirs.length === 1 && files.length === 0) {
      const only = dirs[0]
      current = getShareurl(root, { fid: only.fid, name: only.name })
      continue
    }

    if (dirs.length > 1 && files.length === 0) {
      const picked = [...dirs].sort((a, b) => toTs(b.updated_at) - toTs(a.updated_at))[0]
      if (!picked) break
      current = getShareurl(root, { fid: picked.fid, name: picked.name })
      continue
    }

    break
  }

  if (current !== input) {
    shareAuto.lastResolved = current
    state.shareurl = current
    state.startfid = null
    ElMessage.success('已自动定位到分享目录')
  }

  if (!sawVideo) {
    const files = (lastItems || []).filter((x) => x && !x.is_dir)
    if (!files.some((f) => isVideoFile(f.name || f.file_name))) {
      ElMessage.warning('未发现视频文件，该链接可能存在问题')
    }
  }
}

watch(
  () => state.shareurl,
  (value) => {
    if (!props.modelValue) return
    const url = String(value || '').trim()
    if (!url) {
      autoFill.loading = false
      return
    }
    if (url === shareAuto.lastResolved) return
    if (shareAuto.timer) clearTimeout(shareAuto.timer)
    shareAuto.runId += 1
    const runId = shareAuto.runId
    autoFill.runId = runId
    autoFill.loading = true
    autoFill.text = '正在自动定位目录并填写保存路径...'
    shareAuto.timer = setTimeout(async () => {
      try {
        autoFill.text = '正在自动定位分享目录...'
        await autoResolveShareFolder(url, runId)
      } catch {
        if (autoFill.runId === runId) autoFill.loading = false
        return
      }
      try {
        autoFill.text = '正在自动填写保存路径...'
        await autoFillSavepath(runId)
      } catch {
        if (autoFill.runId === runId) autoFill.loading = false
        return
      }
      if (autoFill.runId === runId) autoFill.loading = false
    }, 800)
  },
)

watch(
  () => [state.taskname, state.tmdb_id, state.tmdb_media_type, state.account_choice] as const,
  () => {
    if (!props.modelValue) return
    if (!String(state.shareurl || '').trim()) return
    if (saveAuto.timer) clearTimeout(saveAuto.timer)
    const runId = shareAuto.runId
    saveAuto.timer = setTimeout(() => {
      autoFillSavepath(runId).catch(() => {
        return
      })
    }, 350)
  },
)

watch(
  () => state.taskname,
  (value) => {
    if (!props.modelValue) return
    const q = sanitizeSuggestionQuery(value)
    if (q.length < 2) {
      taskSuggestions.items = []
      return
    }
    scheduleLightSearch()
  },
)

watch(
  () => props.modelValue,
  (visible) => {
    if (!visible) {
      resetSuggestions()
    }
  },
)
</script>

<template>
  <el-drawer :model-value="modelValue" :title="isEditing ? '编辑追剧任务' : '新增追剧任务'" :size="isMobile ? '100%' : '620px'" @close="closeDrawer">
    <el-form
      v-loading="autoFill.loading"
      :element-loading-text="autoFill.text"
      element-loading-background="rgba(0,0,0,0.55)"
      label-position="top"
      class="drawer-form"
      :disabled="Boolean(submitting) || autoFill.loading"
    >
      <el-alert v-if="isEditing && props.task?.shareurl_ban" type="warning" show-icon :closable="false" style="margin-bottom: 14px">
        <div style="font-size: 13px; line-height: 1.5">
          <div>分享链接异常已封禁：{{ props.task?.shareurl_ban }}</div>
          <div>保存后会自动清除封禁并重新尝试执行。</div>
        </div>
      </el-alert>
      <el-alert v-if="autoFill.loading" type="info" show-icon :closable="false" style="margin-bottom: 14px">
        <div style="font-size: 13px; line-height: 1.5">
          <div>{{ autoFill.text }}</div>
          <div>自动完成后可继续手动修改。</div>
        </div>
      </el-alert>
      <div class="drawer-form__section">
        <div class="drawer-form__section-title">基础信息</div>
        <el-form-item label="任务名称">
          <el-input v-model="state.taskname" placeholder="例如：某电视剧" @focus="showSuggestions" @blur="hideSuggestionsLater">
            <template #append>
              <el-button
                :disabled="sanitizeSuggestionQuery(state.taskname).length < 2"
                :loading="taskSuggestions.loading && taskSuggestions.deep === 1"
                @mousedown.prevent
                @click="searchSuggestions(1)"
              >
                深度搜索
              </el-button>
            </template>
          </el-input>
          <div v-if="taskSuggestions.visible" class="task-suggestions">
            <div class="task-suggestions__tip">
              <span v-if="taskSuggestions.verifying">正在检查链接有效性...</span>
              <span v-else>
                {{
                  taskSuggestions.notice
                    ? taskSuggestions.notice
                    : taskSuggestions.items.length
                      ? '以下资源来自网络搜索，请自行辨识'
                      : '未搜索到资源'
                }}
              </span>
            </div>
            <div
              v-for="(item, idx) in taskSuggestions.items"
              :key="`${item.shareurl}-${idx}`"
              class="task-suggestions__item"
              @mousedown.prevent
              @click="selectSuggestion(item)"
              :title="item.content || ''"
            >
              <span class="task-suggestions__icon">{{ item.verify === true ? '✅' : item.verify === false ? '❌' : '❔' }}</span>
              <span class="task-suggestions__name">{{ item.taskname }}</span>
              <el-link class="task-suggestions__url" :href="item.shareurl" target="_blank" @click.stop>{{ item.shareurl }}</el-link>
              <el-tag size="small" type="success" effect="plain">{{ item.source || '网络公开' }}</el-tag>
              <el-tag v-if="item.channel" size="small" type="info" effect="plain">{{ item.channel }}</el-tag>
              <el-tag v-if="item.datetime" size="small" effect="plain">{{ item.datetime }}</el-tag>
              <el-tag v-if="item.max_video" size="small" type="warning" effect="plain">文件最大</el-tag>
            </div>
          </div>
        </el-form-item>
        <el-form-item label="关联 TMDB（可选）">
          <div class="drawer-form__switch-row" style="justify-content: flex-start; gap: 10px; flex-wrap: wrap">
            <el-tag v-if="tmdbBindLabel()" type="success" effect="plain">{{ tmdbBindLabel() }}</el-tag>
            <el-tag v-else type="info" effect="plain">未关联</el-tag>
            <el-button size="small" @click="openTmdbLinkDialog">搜索关联</el-button>
            <el-button size="small" type="danger" plain :disabled="!state.tmdb_id" @click="clearTmdbLink">解除关联</el-button>
          </div>
        </el-form-item>
        <el-form-item label="分享链接">
          <el-input v-model="state.shareurl" placeholder="https://...">
            <template #append>
              <el-button :disabled="!state.shareurl" @click="openSharePicker">选择文件夹</el-button>
            </template>
          </el-input>
        </el-form-item>
        <el-form-item label="使用账号">
          <el-select v-model="state.account_choice" style="width: 100%">
            <el-option label="自动选择（按分享链接）" value="__AUTO__" />
            <el-option v-if="unavailableSelectedAccount" :key="`unavailable-${state.account_choice}`" :label="unavailableSelectedAccountLabel" :value="state.account_choice" disabled />
            <el-option v-for="item in activeAccounts" :key="item.id" :label="`${item.name}（${item.drive_type}）`" :value="item.name" />
          </el-select>
          <div v-if="state.account_choice === '__AUTO__'" class="drawer-form__hint">
            自动模式下会优先选择与分享链接同类型的默认账号。
          </div>
        </el-form-item>
        <div class="drawer-form__switch-row">
          <el-switch v-model="state.enabled" active-text="启用任务" inactive-text="禁用任务" />
        </div>
      </div>

      <div class="drawer-form__section">
        <div class="drawer-form__section-title">保存目录</div>
        <el-form-item label="保存路径（savepath）">
          <el-input v-model="state.savepath" placeholder="/剧集/某电视剧" />
        </el-form-item>
        <div class="drawer-form__switch-row">
          <el-button @click="openDrivePicker">选择目录</el-button>
        </div>
      </div>

      <div class="drawer-form__section">
        <div class="drawer-form__section-title">保存规则</div>
        <el-form-item label="内置规则（可选）">
          <el-select
            v-model="magicRegex.selectedKey"
            style="width: 100%"
            clearable
            filterable
            :loading="magicRegex.loading"
            placeholder="选择内置规则后会自动填入下方输入框"
            @change="applyMagicRule"
          >
            <el-option v-for="rule in magicRegex.rules" :key="rule.key" :label="rule.label ? `${rule.label}（${rule.key}）` : rule.key" :value="rule.key" />
          </el-select>
          <div class="drawer-form__hint">选择后会把默认 pattern / replace 填入输入框，可继续修改。</div>
        </el-form-item>
        <el-form-item label="匹配表达式（pattern）">
          <el-input v-model="state.pattern" placeholder="$TV_REGEX 或正则表达式" />
          <div v-if="activeMagicRule" class="drawer-form__hint">内置规则实际正则：{{ activeMagicRule.pattern }}</div>
        </el-form-item>
        <el-form-item label="替换表达式（replace）">
          <el-input v-model="state.replace" placeholder="\1E\2.\3" />
        </el-form-item>
        <div class="drawer-form__switch-row">
          <el-switch v-model="state.ignore_extension" active-text="忽略后缀判重" inactive-text="严格判重" />
        </div>
        <el-form-item label="排序基数（sort_index）">
          <el-input-number v-model="state.sort_index" :min="1" style="width: 100%" />
        </el-form-item>
        <el-form-item label="文件起始（startfid）">
          <el-input v-model="state.startfid" placeholder="可选，只转存修改日期 > 此文件的文件">
            <template #append>
              <el-button :disabled="!state.shareurl" @click="openStartfidPicker">选择</el-button>
            </template>
          </el-input>
        </el-form-item>
      </div>

      <div class="drawer-form__section">
        <div class="drawer-form__section-title">更新与时间</div>
        <el-form-item label="需转存的文件夹（update_subdir，正则）">
          <el-input v-model="state.update_subdir" placeholder="例如：^更新$ 或 ^第\\d+季$（留空表示不处理分享中的目录）" />
        </el-form-item>
        <el-form-item label="更新目录重存模式">
          <el-select v-model="state.update_subdir_resave_mode" style="width: 100%">
            <el-option label="不重存" value="none" />
            <el-option label="删除后重存" value="delete_then_resave" />
          </el-select>
        </el-form-item>
        <el-form-item label="截止日期（YYYY-MM-DD）">
          <el-input v-model="state.enddate" placeholder="例如：2099-12-31" />
        </el-form-item>
        <el-form-item label="运行星期">
          <div class="drawer-form__switch-row" style="justify-content: flex-start; gap: 10px; flex-wrap: wrap">
            <el-radio-group v-model="state.runweek_mode">
              <el-radio-button label="auto" :disabled="autoRunweekDisabled">自动</el-radio-button>
              <el-radio-button label="manual">手动</el-radio-button>
            </el-radio-group>
            <div v-if="state.runweek_mode === 'auto'" class="drawer-form__hint" style="margin: 0">
              <span v-if="!tmdbLink.configured">请先在系统设置配置 TMDB</span>
              <span v-else-if="autoRunweekText">已识别：{{ autoRunweekText }}</span>
              <span v-else>识别中…</span>
            </div>
          </div>
          <el-checkbox-group v-if="state.runweek_mode === 'manual'" v-model="state.runweek">
            <el-checkbox v-for="item in weekOptions" :key="item.value" :label="item.value">{{ item.label }}</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
      </div>

      <div class="drawer-form__section">
        <div class="drawer-form__section-title">插件选项</div>
        <div v-if="!plugins.length" class="empty-copy">暂无插件。</div>
        <div v-else class="plugin-stack">
          <div v-for="plugin in plugins" :key="plugin.plugin_key" class="plugin-block">
            <div class="plugin-block__title">{{ plugin.plugin_key }}</div>
            <el-form-item v-for="field in plugin.task_config_fields || []" :key="field.key" :label="field.label || field.key">
              <el-switch
                v-if="field.input_type === 'switch'"
                v-model="state.addition[plugin.plugin_key][field.key]"
                active-text="开启"
                inactive-text="关闭"
              />
              <el-input-number v-else-if="field.input_type === 'number'" v-model="state.addition[plugin.plugin_key][field.key]" style="width: 100%" />
              <el-input
                v-else-if="field.input_type === 'textarea'"
                v-model="state.addition[plugin.plugin_key][field.key]"
                type="textarea"
                :rows="field.secret ? 4 : 3"
                :placeholder="field.placeholder || ''"
              />
              <el-input
                v-else
                v-model="state.addition[plugin.plugin_key][field.key]"
                :type="field.input_type === 'password' ? 'password' : 'text'"
                :placeholder="field.placeholder || ''"
                :show-password="field.input_type === 'password'"
              />
              <div v-if="field.description" class="drawer-form__hint">{{ field.description }}</div>
            </el-form-item>
          </div>
        </div>
      </div>

    </el-form>

    <template #footer>
      <div class="drawer-form__footer">
        <el-button @click="closeDrawer">取消</el-button>
        <el-button type="success" plain :disabled="submitting" @click="runOnce">运行一次</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">保存</el-button>
      </div>
    </template>

    <el-dialog v-model="tmdbLink.visible" title="关联 TMDB" :width="isMobile ? '96vw' : '860px'">
      <div v-loading="tmdbLink.loading">
        <div class="drawer-form__switch-row" style="justify-content: flex-start; gap: 10px; flex-wrap: wrap; margin-bottom: 12px">
          <el-select v-model="tmdbLink.type" style="width: 120px">
            <el-option label="电视剧" value="tv" />
            <el-option label="电影" value="movie" />
          </el-select>
          <el-input v-model="tmdbLink.q" placeholder="关键词（默认使用任务名）" style="flex: 1; min-width: 220px" @keyup.enter="runTmdbLinkSearch" />
          <el-input v-model="tmdbLink.year" placeholder="年份(可选)" style="width: 120px" @keyup.enter="runTmdbLinkSearch" />
          <el-button type="primary" :disabled="!tmdbLink.q.trim()" @click="runTmdbLinkSearch">搜索</el-button>
        </div>

        <div v-if="!tmdbLink.configured" class="drawer-form__hint">未配置 TMDB API Key。</div>
        <el-table
          v-else
          :data="tmdbLink.items"
          class="tmdb-link-table"
          style="width: 100%"
          highlight-current-row
          row-key="id"
          @current-change="
            (row) => {
              tmdbLink.selectedId = Number(row?.id) || 0
              if (tmdbLink.selectedId) ensureTmdbLinkDetail(tmdbLink.selectedId)
            }
          "
        >
          <el-table-column label="海报" width="70">
            <template #default="{ row }">
              <el-image
                v-if="posterUrlFromTMDB(row.poster_path)"
                :src="posterUrlFromTMDB(row.poster_path)"
                fit="cover"
                style="width: 48px; height: 72px; border-radius: 6px"
              />
            </template>
          </el-table-column>
          <el-table-column label="影视" min-width="520">
            <template #default="{ row }">
              <div class="title">
                <div class="title__main">{{ tmdbLink.type === 'movie' ? row.title : row.name }}</div>
                <div class="title__sub">
                  <span>{{ tmdbLink.type === 'movie' ? row.release_date : row.first_air_date }}</span>
                  <span v-if="row.vote_average != null"> · {{ Number(row.vote_average).toFixed(1) }}</span>
                </div>
                <div v-if="tmdbLinkRowProgress(row)" class="title__sub">{{ tmdbLinkRowProgress(row) }}</div>
              </div>
            </template>
          </el-table-column>
        </el-table>
        <div v-if="tmdbLink.configured && !tmdbLink.items.length" class="drawer-form__hint" style="margin-top: 10px">暂无结果。</div>
      </div>
      <template #footer>
        <el-button @click="tmdbLink.visible = false">取消</el-button>
        <el-button type="primary" :disabled="!tmdbLink.selectedId" @click="confirmTmdbLink">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="drivePicker.visible" title="选择保存目录" :width="shareDialogWidth" :fullscreen="isMobile">
      <div class="drawer-form__section" style="margin-bottom: 12px">
        <div class="drawer-form__switch-row">
          <el-button :loading="drivePicker.loading" @click="refreshDrivePicker">刷新</el-button>
          <el-button @click="driveGoRoot">根目录</el-button>
          <el-button v-if="drivePicker.paths.length" @click="driveGoBack">返回上级</el-button>
          <el-button type="primary" @click="useCurrentDrivePath(false)">当前文件夹</el-button>
          <el-button v-if="state.taskname.trim()" type="primary" @click="useCurrentDrivePath(true)">当前文件夹/{{ state.taskname.trim() }}</el-button>
        </div>
        <div class="drawer-form__hint" style="margin-top: 10px">当前路径：{{ currentDrivePathLabel() }}</div>
        <el-breadcrumb v-if="drivePicker.paths.length" separator="/">
          <el-breadcrumb-item>
            <a href="#" @click.prevent="driveGoRoot">/</a>
          </el-breadcrumb-item>
          <el-breadcrumb-item v-for="(item, idx) in drivePicker.paths" :key="item.fid">
            <a
              v-if="idx !== drivePicker.paths.length - 1"
              href="#"
              @click.prevent="driveNavigateTo(item.fid, item.name, { sliceToIndex: idx })"
            >
              {{ item.name }}
            </a>
            <span v-else class="text-muted">{{ item.name }}</span>
          </el-breadcrumb-item>
        </el-breadcrumb>
        <div v-if="isMobile" style="display: flex; justify-content: flex-end; margin-top: 10px">
          <el-select v-model="drivePicker.mobileSort" size="small" style="width: 150px" @change="applyDriveMobileSort">
            <el-option label="文件名 ↑" value="file_name:asc" />
            <el-option label="文件名 ↓" value="file_name:desc" />
            <el-option label="修改日期 ↑" value="updated_at:asc" />
            <el-option label="修改日期 ↓" value="updated_at:desc" />
          </el-select>
        </div>
      </div>
      <el-table
        :data="drivePicker.items"
        v-loading="drivePicker.loading"
        size="small"
        style="width: 100%"
        @row-click="enterDriveDir"
        @sort-change="onDriveSortChange"
      >
        <el-table-column prop="file_name" label="文件名" min-width="260" sortable="custom">
          <template #default="{ row }">
            <span>{{ row.file_name || row.name }}</span>
            <el-tag v-if="row.is_dir" size="small" type="info" style="margin-left: 8px">目录</el-tag>
            <el-tag v-else size="small" type="success" style="margin-left: 8px">文件</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="130">
          <template #default="{ row }">
            <span v-if="row.is_dir">{{ row.include_items != null ? `${row.include_items}项` : '-' }}</span>
            <span v-else>{{ formatSize(row.size) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="updated_at" label="修改日期" width="170" sortable="custom">
          <template #default="{ row }">
            <span>{{ formatTs(row.updated_at) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="sharePicker.visible" title="选择需转存的文件夹" :width="shareDialogWidth" :fullscreen="isMobile">
      <div class="drawer-form__section" style="margin-bottom: 12px">
        <div class="drawer-form__switch-row">
          <el-button :loading="sharePicker.loading" @click="refreshSharePicker(sharePicker.pdir_fid)">刷新</el-button>
          <el-button v-if="sharePicker.stack.length" @click="goShareBack">返回上级</el-button>
          <el-button type="primary" :disabled="!sharePicker.stack.length" @click="pickShareFolderCurrent">使用当前文件夹</el-button>
        </div>
        <div v-if="sharePicker.stack.length" class="drawer-form__hint" style="margin-top: 10px">
          当前路径：/{{ sharePicker.stack.filter((x) => x.name !== '当前目录').map((x) => x.name).join('/') }}
        </div>
      </div>
      <el-table :data="sharePicker.items" v-loading="sharePicker.loading" size="small" style="width: 100%" @row-click="onShareRowClick">
        <el-table-column label="名称" min-width="280">
          <template #default="{ row }">
            <span>{{ row.file_name || row.name }}</span>
            <el-tag v-if="row.is_dir" size="small" type="info" style="margin-left: 8px">目录</el-tag>
            <el-tag v-else size="small" type="success" style="margin-left: 8px">文件</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="130">
          <template #default="{ row }">
            <span v-if="row.is_dir">{{ (row.include_items ?? row.children_count) != null ? `${row.include_items ?? row.children_count}项` : '-' }}</span>
            <span v-else>{{ formatSize(row.size) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="正则处理" min-width="240">
          <template #default="{ row }">
            <span
              v-if="row.file_name_re"
              style="color: var(--el-color-success)"
            >
              {{ row.file_name_re }}
            </span>
            <span
              v-else-if="row.file_name_saved"
              style="color: var(--el-text-color-secondary)"
            >
              {{ row.file_name_saved }}
            </span>
            <span v-else style="color: var(--el-color-danger)">x</span>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="170" sortable :sort-method="sortUpdatedAt">
          <template #default="{ row }">
            <span>{{ formatTs(row.updated_at) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="startfidPicker.visible" title="选择起始文件" :width="shareDialogWidth" :fullscreen="isMobile">
      <div class="drawer-form__section" style="margin-bottom: 12px">
        <div class="drawer-form__hint">点击文件行即可选择 startfid。</div>
      </div>
      <el-table :data="startfidPicker.items" v-loading="startfidPicker.loading" size="small" style="width: 100%" @row-click="selectStartfid">
        <el-table-column label="文件名" min-width="320">
          <template #default="{ row }">
            <span>{{ row.file_name || row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="130">
          <template #default="{ row }">
            <span>{{ formatSize(row.size) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="正则处理" min-width="260">
          <template #default="{ row }">
            <span
              v-if="row.file_name_re"
              style="color: var(--el-color-success)"
            >
              {{ row.file_name_re }}
            </span>
            <span
              v-else-if="row.file_name_saved"
              style="color: var(--el-text-color-secondary)"
            >
              {{ row.file_name_saved }}
            </span>
            <span v-else style="color: var(--el-color-danger)">x</span>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="170" sortable :sort-method="sortUpdatedAt">
          <template #default="{ row }">
            <span>{{ formatTs(row.updated_at) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </el-drawer>
</template>

<style scoped>
.drawer-form {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.drawer-form__section {
  padding: 18px;
  border-radius: 20px;
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
}

.drawer-form__section-title {
  margin-bottom: 14px;
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.drawer-form__switch-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.drawer-form__hint {
  margin-top: 6px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.task-suggestions {
  margin-top: 10px;
  padding: 10px;
  border-radius: 14px;
  border: 1px solid var(--el-border-color-lighter);
  background: var(--el-fill-color-blank);
  max-height: 260px;
  overflow: auto;
}

.task-suggestions__tip {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  padding: 2px 4px 8px 4px;
}

.task-suggestions__item {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px;
  border-radius: 12px;
  cursor: pointer;
}

.task-suggestions__item:hover {
  background: var(--el-fill-color);
}

.task-suggestions__icon {
  width: 18px;
  text-align: center;
}

.task-suggestions__name {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.task-suggestions__url {
  font-size: 12px;
  max-width: 100%;
}

.drawer-form__footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  width: 100%;
}

.plugin-stack {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.plugin-block {
  padding: 14px;
  border-radius: 16px;
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
}

.plugin-block__title {
  font-weight: 600;
  margin-bottom: 10px;
  color: var(--el-text-color-primary);
}

:deep(.tmdb-link-table .el-table__cell .cell) {
  white-space: normal;
}

:deep(.tmdb-link-table .title__main) {
  font-weight: 600;
  color: var(--el-text-color-primary);
}

:deep(.tmdb-link-table .title__sub) {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.5;
  margin-top: 2px;
}
</style>
