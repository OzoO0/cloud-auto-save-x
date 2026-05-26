<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'

import DramaTaskDrawer from '@/components/tasks/DramaTaskDrawer.vue'
import {
  createTask,
  deleteTask,
  fetchTaskSchedulerSetting,
  fetchTasks,
  repairBannedDramaTasks,
  syncDramaSavepathSnapshots,
  stopCompletedDramaTasks,
  setTaskStatus,
  updateTask,
  updateTaskSchedulerSetting,
} from '@/api/tasks'
import { fetchDriveAccounts, fetchPlugins } from '@/api/extensions'
import { TASK_RUN, TASK_WRITE } from '@/constants/permissions'
import { useAuthStore } from '@/stores/auth'
import type { DriveAccountItem, PluginItem } from '@/types/extensions'
import type { TaskItem, TaskSchedulerSetting } from '@/types/tasks'
import { validateCrontab5, validateTimezone } from '@/utils/cron'

const auth = useAuthStore()
const canWrite = computed(() => auth.permissions.includes(TASK_WRITE))
const canRun = computed(() => auth.permissions.includes(TASK_RUN))

const loading = ref(false)
const submitting = ref(false)
const tasks = ref<TaskItem[]>([])
const accounts = ref<DriveAccountItem[]>([])
const plugins = ref<PluginItem[]>([])
const scheduler = ref<TaskSchedulerSetting | null>(null)
const schedulerSaving = ref(false)
const repairSaving = ref(false)
const stopCompletedSaving = ref(false)
const syncSnapshotsSaving = ref(false)

const drawerVisible = ref(false)
const currentTask = ref<TaskItem | null>(null)

const runLogDialog = reactive({
  visible: false,
  title: '执行日志',
  content: '',
  status: '',
  stage: '',
  message: '',
  taskId: 0,
})

type RunAllLogItem = {
  taskId: number
  taskname: string
  status: string
  stage: string
  message: string
  content: string
}

const runAllDialog = reactive({
  visible: false,
  title: '执行全部：日志',
  running: false,
  stopRequested: false,
  items: [] as RunAllLogItem[],
  activeNames: [] as Array<string | number>,
})

const deleteDialog = reactive({
  visible: false,
  loading: false,
  task: null as TaskItem | null,
})

const runLogPre = ref<HTMLElement | null>(null)
let runLogController: AbortController | null = null
let runAllController: AbortController | null = null
const runAllPreRefs = new Map<number, HTMLElement>()

function setRunAllPreRef(taskId: number) {
  return (el: any) => {
    if (el) runAllPreRefs.set(taskId, el as HTMLElement)
    else runAllPreRefs.delete(taskId)
  }
}

const viewport = reactive({ width: window.innerWidth })
const isMobile = computed(() => viewport.width <= 768)
const isPad = computed(() => viewport.width > 768 && viewport.width <= 1024)
const showAllActions = computed(() => isMobile.value || viewport.width > 1024)

const runAllStats = computed(() => {
  const items = runAllDialog.items
  const stats: Record<string, number> = {
    pending: 0,
    running: 0,
    success: 0,
    failed: 0,
    skipped: 0,
    aborted: 0,
    unknown: 0,
  }
  for (const item of items) {
    const key = String(item.status || 'unknown')
    if (Object.prototype.hasOwnProperty.call(stats, key)) stats[key] += 1
    else stats.unknown += 1
  }
  return stats
})

function onResize() {
  viewport.width = window.innerWidth
}

const filters = reactive({
  keyword: '',
  status: 'all',
})

const accountByName = computed(() => new Map(accounts.value.map((item) => [item.name, item])))

function detectDriveTypeFromUrl(url: string) {
  if (!url) return null
  if (/pan\.quark\.cn/.test(url)) return 'quark'
  if (/(?:115|anxia|115cdn)\.com/.test(url)) return '115'
  if (/pan\.baidu\.com/.test(url)) return 'baidu'
  if (/pan\.xunlei\.com/.test(url)) return 'xunlei'
  if (/(?:alipan|aliyundrive)\.com/.test(url)) return 'aliyun'
  if (/drive\.uc\.cn/.test(url)) return 'uc'
  if (/(?:123pan|123865|123684|123952|123912)\.com/.test(url)) return '123pan'
  if (/(?:cloud|m\.cloud)\.189\.cn/.test(url)) return 'cloud189'
  return null
}

function pickDefaultAccountByType(driveType: string) {
  return (
    accounts.value.find((acc) => acc.enabled && acc.drive_type === driveType && acc.is_default) ||
    accounts.value.find((acc) => acc.enabled && acc.drive_type === driveType) ||
    null
  )
}

function formatAccountLabel(task: TaskItem) {
  const name = String(task.account_name || '').trim()
  if (name) {
    const acc = accountByName.value.get(name)
    const driveType = acc?.drive_type || detectDriveTypeFromUrl(task.shareurl)
    return driveType ? `${name}（${driveType}）` : name
  }
  const driveType = detectDriveTypeFromUrl(task.shareurl)
  const auto = driveType ? pickDefaultAccountByType(driveType) : null
  if (auto && driveType) return `自动：${auto.name}（${driveType}）`
  if (driveType) return `自动（${driveType}）`
  return '自动'
}

function formatEpisode(season?: number | null, episode?: number | null) {
  const sn = Number(season)
  const ep = Number(episode)
  if (!Number.isFinite(sn) || sn <= 0 || !Number.isFinite(ep) || ep <= 0) return '-'
  return `S${String(sn).padStart(2, '0')}E${String(ep).padStart(2, '0')}`
}

function progressTagText(task: TaskItem) {
  if (!(task.tmdb_id && task.tmdb_media_type === 'tv')) return '-'
  const p = task.drama_update_progress
  if (!p) return '未知'
  if (p.available && p.is_latest) return '最新'
  if (p.available && typeof p.behind_episodes === 'number') return `落后 ${p.behind_episodes} 集`
  return '未知'
}

function progressTagType(task: TaskItem) {
  if (!(task.tmdb_id && task.tmdb_media_type === 'tv')) return 'info'
  const p = task.drama_update_progress
  if (p?.available && p.is_latest) return 'success'
  if (p?.available && typeof p.behind_episodes === 'number') return p.behind_episodes > 0 ? 'warning' : 'success'
  return 'info'
}

function progressTooltip(task: TaskItem) {
  const p = task.drama_update_progress
  if (!p) return null
  return {
    saved: formatEpisode(p.saved_season, p.saved_episode),
    latest: formatEpisode(p.tmdb_season, p.tmdb_episode),
    snapshot: p.snapshot_captured_at || '-',
    reason: p.reason || '',
  }
}

const filteredTasks = computed(() =>
  tasks.value
    .filter((item) => item.task_type === 'drama')
    .filter((item) => {
      const matchesKeyword =
        !filters.keyword ||
        [item.taskname, item.shareurl, item.savepath, formatAccountLabel(item)]
          .filter(Boolean)
          .some((value) => String(value || '').toLowerCase().includes(filters.keyword.toLowerCase()))
      const matchesStatus =
        filters.status === 'all' ||
        (filters.status === 'enabled' && item.enabled) ||
        (filters.status === 'disabled' && !item.enabled)
      return matchesKeyword && matchesStatus
    }),
)

const activePlugins = computed(() => {
  return [...plugins.value]
    .filter((item) => Boolean(item.installed) && Boolean(item.enabled))
    .sort((a, b) => {
      const ap = Number(a.priority) || 0
      const bp = Number(b.priority) || 0
      if (ap !== bp) return ap - bp
      return String(a.plugin_key).localeCompare(String(b.plugin_key))
    })
})

async function loadData() {
  loading.value = true
  try {
    const [taskData, pluginData, accountData, schedulerData] = await Promise.all([
      fetchTasks(),
      fetchPlugins(),
      fetchDriveAccounts(),
      fetchTaskSchedulerSetting(),
    ])
    tasks.value = taskData
    plugins.value = pluginData
    accounts.value = accountData
    scheduler.value = schedulerData
  } finally {
    loading.value = false
  }
}

async function refreshPluginsIfNeeded() {
  try {
    plugins.value = await fetchPlugins()
  } catch {
    return
  }
}

function openCreateDrawer() {
  currentTask.value = null
  drawerVisible.value = true
}

function openEditDrawer(row: TaskItem) {
  currentTask.value = row
  drawerVisible.value = true
}

watch(
  drawerVisible,
  async (visible) => {
    if (!visible) return
    await refreshPluginsIfNeeded()
  },
  { immediate: false },
)

async function submitTask(payload: any) {
  submitting.value = true
  try {
    if (currentTask.value) {
      await updateTask(currentTask.value.id, payload)
      await ElMessageBox.alert('任务已更新', '保存成功', { type: 'success', confirmButtonText: '确定' })
    } else {
      await createTask(payload)
      await ElMessageBox.alert('任务已创建', '保存成功', { type: 'success', confirmButtonText: '确定' })
    }
    drawerVisible.value = false
    await loadData()
  } catch (e: any) {
    const msg = formatTaskSaveError(e)
    if (msg) {
      await ElMessageBox.alert(msg, '保存失败', { type: 'error', confirmButtonText: '确定' })
    }
  } finally {
    submitting.value = false
  }
}

function formatTaskSaveError(e: any): string | null {
  const status = Number(e?.response?.status || 0)
  const data = e?.response?.data

  const msg = String(data?.message || '').trim()
  if (msg) return msg

  const detail = data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail.trim()

  if (status === 422 && Array.isArray(detail)) {
    const fieldMap: Record<string, string> = {
      taskname: '任务名称',
      shareurl: '分享链接',
      savepath: '保存路径（savepath）',
      task_type: '任务类型',
      tmdb_id: 'TMDB ID',
      tmdb_media_type: 'TMDB 类型',
      account_name: '账号',
      update_subdir: '更新子目录',
      startfid: '起始文件',
      enddate: '截止日期',
    }
    const missing: string[] = []
    const issues: string[] = []
    for (const item of detail) {
      if (!item || typeof item !== 'object') continue
      const loc = Array.isArray((item as any).loc) ? (item as any).loc : []
      const fieldKey = String(loc.at(-1) || '').trim()
      const label = fieldMap[fieldKey] || fieldKey || '参数'
      const rawMsg = String((item as any).msg || '').trim()
      if (!rawMsg) continue
      if (rawMsg.toLowerCase().includes('field required')) {
        if (!missing.includes(label)) missing.push(label)
      } else {
        issues.push(`${label}：${rawMsg}`)
      }
    }
    if (missing.length) return `缺少：${missing.join('、')}`
    if (issues.length) return `保存失败：${issues.slice(0, 3).join('；')}`
    return '保存失败：参数校验异常'
  }

  const fallback = String(e?.message || '').trim()
  return fallback || '保存失败'
}

async function handleToggle(row: TaskItem, enabled: boolean) {
  await setTaskStatus(row.id, enabled)
  ElMessage.success('状态已更新')
  await loadData()
}

function openDeleteDialog(row: TaskItem) {
  deleteDialog.task = row
  deleteDialog.visible = true
}

function closeDeleteDialog() {
  if (deleteDialog.loading) return
  deleteDialog.visible = false
  deleteDialog.task = null
}

async function confirmDelete() {
  const task = deleteDialog.task
  if (!task) return
  deleteDialog.loading = true
  try {
    await deleteTask(task.id)
    const name = String(task.taskname || '').trim()
    ElMessage({
      type: 'success',
      message: name ? `已删除任务：${name}` : '已删除任务',
      showClose: true,
      duration: 2200,
    })
    deleteDialog.visible = false
    deleteDialog.task = null
    await loadData()
  } finally {
    deleteDialog.loading = false
  }
}

function handleRowCommand(command: string, row: TaskItem) {
  if (command === 'edit') {
    openEditDrawer(row)
    return
  }
  if (command === 'delete') {
    openDeleteDialog(row)
  }
}

async function handleRunStream(opts: { title: string; url: string; body?: any; taskId?: number; reloadAfter?: boolean }) {
  if (runLogController) runLogController.abort()
  runLogController = new AbortController()

  runLogDialog.status = 'running'
  runLogDialog.stage = ''
  runLogDialog.message = ''
  runLogDialog.content = ''
  runLogDialog.title = opts.title
  runLogDialog.visible = true
  runLogDialog.taskId = Number(opts.taskId) || 0

  function appendLine(text: string) {
    runLogDialog.content += `${text}\n`
    nextTick(() => {
      const el = runLogPre.value
      if (!el) return
      el.scrollTop = el.scrollHeight
    })
  }

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
    if (opts.body != null) headers['Content-Type'] = 'application/json'
    const response = await fetch(opts.url, {
      method: 'POST',
      headers,
      body: opts.body != null ? JSON.stringify(opts.body) : undefined,
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
          appendLine(String(data?.line ?? ''))
          continue
        }
        if (parsed.eventType === 'done') {
          runLogDialog.status = String(data?.status || '')
          runLogDialog.message = String(data?.message || '')
          const exe = data?.execution || null
          if (!runLogDialog.stage) {
            const s = String(exe?.stage || '')
            if (s) runLogDialog.stage = s
          }
          if (!String(runLogDialog.content || '').trim()) {
            const full = String(exe?.run_log || '')
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
          if (opts.reloadAfter) await loadData()
          return
        }
      }
    }
    if (runLogDialog.status === 'running') {
      if (opts.reloadAfter) await loadData()
      const id = Number(runLogDialog.taskId) || 0
      if (id > 0) {
        const task = tasks.value.find((t) => t.id === id)
        const list = Array.isArray(task?.executions) ? task!.executions : []
        const pick = [...list].sort((a: any, b: any) => Date.parse(String(b.started_at || '')) - Date.parse(String(a.started_at || '')))[0]
        if (pick) {
          if (!runLogDialog.stage) runLogDialog.stage = String(pick.stage || '')
          if (!String(runLogDialog.content || '').trim()) runLogDialog.content = String(pick.run_log || '')
          runLogDialog.status = String(pick.status || '')
          runLogDialog.message = String(pick.message || '')
        }
      }
    }
  } catch (e: any) {
    if (e?.name === 'AbortError') {
      if (opts.reloadAfter) await loadData()
      const id = Number(runLogDialog.taskId) || 0
      if (id > 0) {
        const task = tasks.value.find((t) => t.id === id)
        const list = Array.isArray(task?.executions) ? task!.executions : []
        const pick = [...list].sort((a: any, b: any) => Date.parse(String(b.started_at || '')) - Date.parse(String(a.started_at || '')))[0]
        if (pick) {
          if (!runLogDialog.stage) runLogDialog.stage = String(pick.stage || '')
          if (!String(runLogDialog.content || '').trim()) runLogDialog.content = String(pick.run_log || '')
          runLogDialog.status = String(pick.status || '')
          runLogDialog.message = String(pick.message || '')
        }
      }
      return
    }
    runLogDialog.status = 'failed'
    runLogDialog.message = e?.message || String(e || '')
    ElMessage.error(runLogDialog.message || '任务执行失败')
  }
}

async function handleRun(row: TaskItem) {
  await handleRunStream({
    title: `执行日志：${row.taskname}`,
    url: `/api/tasks/${row.id}/run/stream`,
    taskId: Number(row.id) || 0,
    reloadAfter: true,
  })
}

async function handleRunOnce(payload: any) {
  await handleRunStream({
    title: `运行一次：${String(payload?.taskname || '').trim() || '未命名任务'}`,
    url: `/api/tasks/run/stream`,
    body: payload,
    taskId: 0,
    reloadAfter: false,
  })
}

function stopRunLogStream() {
  if (!runLogController) return
  runLogController.abort()
  runLogController = null
}

function stopRunAllStream() {
  runAllDialog.stopRequested = true
  if (!runAllController) return
  runAllController.abort()
  runAllController = null
}

async function copyRunAllLog() {
  const blocks = runAllDialog.items.map((item) => {
    const header = `===== ${item.taskname}（${item.status || 'unknown'}）=====`
    const stage = item.stage ? `阶段：${item.stage}\n` : ''
    const msg = item.message ? `结果：${item.message}\n` : ''
    const body = String(item.content || '').trimEnd()
    return `${header}\n${stage}${msg}${body}`.trimEnd()
  })
  const text = blocks.join('\n\n').trim()
  if (!text) return
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
    } else {
      const textarea = document.createElement('textarea')
      textarea.value = text
      textarea.style.position = 'fixed'
      textarea.style.top = '0'
      textarea.style.left = '0'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      textarea.setSelectionRange(0, 99999)
      document.execCommand('copy')
      document.body.removeChild(textarea)
    }
    ElMessage.success('日志已复制')
  } catch {
    ElMessage.error('复制失败')
  }
}

async function copyRunLog() {
  const text = String(runLogDialog.content || '')
  if (!text) return
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
    } else {
      const textarea = document.createElement('textarea')
      textarea.value = text
      textarea.style.position = 'fixed'
      textarea.style.top = '0'
      textarea.style.left = '0'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      textarea.setSelectionRange(0, 99999)
      document.execCommand('copy')
      document.body.removeChild(textarea)
    }
    ElMessage.success('日志已复制')
  } catch {
    ElMessage.error('复制失败')
  }
}

async function saveScheduler() {
  if (!scheduler.value) return
  const cronCheck = validateCrontab5(scheduler.value.crontab)
  if (!cronCheck.ok) {
    ElMessage.error(cronCheck.message)
    return
  }
  const tzCheck = validateTimezone(scheduler.value.timezone)
  if (!tzCheck.ok) {
    ElMessage.error(tzCheck.message)
    return
  }
  scheduler.value.crontab = cronCheck.normalized || scheduler.value.crontab
  scheduler.value.timezone = tzCheck.normalized || scheduler.value.timezone
  schedulerSaving.value = true
  try {
    scheduler.value = await updateTaskSchedulerSetting({
      enabled: scheduler.value.enabled,
      crontab: scheduler.value.crontab,
      timezone: scheduler.value.timezone,
    })
    ElMessage.success('调度已更新')
  } finally {
    schedulerSaving.value = false
  }
}

async function confirmRunAll() {
  if (runAllDialog.running) return
  try {
    await ElMessageBox.confirm('确认现在手动执行全部“追剧任务”吗？将按当前任务的 runweek/enddate 自动跳过不符合条件的任务。', '手动执行', {
      type: 'warning',
      confirmButtonText: '执行',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  const target = filteredTasks.value.filter((task) => task.enabled)
  const skippedBan = target.filter((task) => Boolean(task.shareurl_ban)).length
  const runnable = target.filter((task) => !task.shareurl_ban)

  runAllDialog.items = runnable.map((task) => ({
    taskId: Number(task.id) || 0,
    taskname: String(task.taskname || '').trim() || `任务 #${task.id}`,
    status: 'pending',
    stage: '',
    message: '',
    content: '',
  }))
  runAllDialog.activeNames = runnable.map((task) => Number(task.id) || 0)
  runAllDialog.title = `执行全部：日志（${runnable.length} 个任务）`
  runAllDialog.visible = true
  runAllDialog.running = true
  runAllDialog.stopRequested = false

  try {
    for (const item of runAllDialog.items) {
      if (runAllDialog.stopRequested) {
        item.status = item.status === 'pending' ? 'aborted' : item.status
        continue
      }

      item.status = 'running'
      item.stage = ''
      item.message = ''
      item.content = ''

      if (runAllController) runAllController.abort()
      runAllController = new AbortController()

      const url = `/api/tasks/${item.taskId}/run/stream`

      function appendLine(text: string) {
        item.content += `${text}\n`
        nextTick(() => {
          const el = runAllPreRefs.get(item.taskId)
          if (!el) return
          el.scrollTop = el.scrollHeight
        })
      }

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
        const response = await fetch(url, { method: 'POST', headers, signal: runAllController.signal })
        if (!response.ok) {
          const text = await response.text().catch(() => '')
          item.status = 'failed'
          item.message = text || `HTTP ${response.status}`
          continue
        }
        const reader = response.body?.getReader()
        if (!reader) {
          item.status = 'failed'
          item.message = '响应不支持流式读取'
          continue
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
              item.status = 'running'
              continue
            }
            if (parsed.eventType === 'stage') {
              item.stage = String(data?.stage || '')
              continue
            }
            if (parsed.eventType === 'log') {
              appendLine(String(data?.line ?? ''))
              continue
            }
            if (parsed.eventType === 'done') {
              item.status = String(data?.status || '')
              item.message = String(data?.message || '')
              const exe = data?.execution || null
              if (!item.stage) {
                const s = String(exe?.stage || '')
                if (s) item.stage = s
              }
              if (!String(item.content || '').trim()) {
                const full = String(exe?.run_log || '')
                if (full) item.content = full
              }
              break
            }
          }
          if (item.status !== 'running') break
        }
        if (item.status === 'running') {
          item.status = 'unknown'
          item.message = '执行结束但未收到 done 事件'
        }
      } catch (e: any) {
        if (e?.name === 'AbortError') {
          item.status = runAllDialog.stopRequested ? 'aborted' : 'aborted'
          item.message = runAllDialog.stopRequested ? '已停止读取' : '读取中断'
          continue
        }
        item.status = 'failed'
        item.message = e?.message || String(e || '')
      } finally {
        runAllController = null
      }
    }
  } finally {
    runAllDialog.running = false
    runAllDialog.stopRequested = false
    await loadData()
    if (skippedBan > 0) ElMessage.warning(`已跳过 ${skippedBan} 个封禁任务`)
  }
}

async function confirmRepairBanned() {
  try {
    await ElMessageBox.confirm(
      '确认现在扫描并修复“封禁/失效”的追剧任务吗？\n\n- 仅处理已启用且 shareurl_ban 非空、已关联 TMDB(tv) 的任务\n- 会自动搜索同网盘资源并替换分享链接\n- 修复成功会单独推送一条通知',
      '修复失效任务',
      {
        type: 'warning',
        confirmButtonText: '开始修复',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  repairSaving.value = true
  try {
    const res = await repairBannedDramaTasks()
    const repaired = Number(res?.repaired || 0)
    const checked = Number(res?.checked || 0)
    if (!repaired) {
      await ElMessageBox.alert(`扫描完成：checked=${checked}，未发现可修复任务。`, '修复结果', { type: 'success', confirmButtonText: '确定' })
    } else {
      const lines = (res?.items || []).map((it) => {
        const s = Number(it?.season || 0)
        const e = Number(it?.episode || 0)
        const se = s > 0 && e > 0 ? `S${String(s).padStart(2, '0')}E${String(e).padStart(2, '0')}` : ''
        const size = it?.size != null ? ` size=${it.size}` : ''
        return `- ${it.taskname} ${se}${size}\n  ${it.new_shareurl || ''}`
      })
      await ElMessageBox.alert(`修复完成：checked=${checked}，repaired=${repaired}\n\n${lines.join('\n')}`, '修复结果', {
        type: 'success',
        confirmButtonText: '确定',
      })
    }
    await loadData()
  } catch (e: any) {
    const msg = String(e?.response?.data?.message || e?.response?.data?.detail || e?.message || '修复失败')
    await ElMessageBox.alert(msg, '修复失败', { type: 'error', confirmButtonText: '确定' })
  } finally {
    repairSaving.value = false
  }
}

async function confirmStopCompleted() {
  try {
    await ElMessageBox.confirm(
      '确认一键停止（禁用）所有“已完结”的追剧任务吗？\n\n- 仅处理：已启用 + 已关联 TMDB(tv)\n- 依据 TMDB 缓存的 status=Ended/Canceled 判断完结',
      '停止已完结任务',
      {
        type: 'warning',
        confirmButtonText: '停止',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  stopCompletedSaving.value = true
  try {
    const res = await stopCompletedDramaTasks()
    const checked = Number(res?.checked || 0)
    const matched = Number(res?.matched || 0)
    const stopped = Number(res?.stopped || 0)
    await ElMessageBox.alert(`处理完成：checked=${checked}，matched=${matched}，stopped=${stopped}`, '停止结果', {
      type: 'success',
      confirmButtonText: '确定',
    })
    await loadData()
  } catch (e: any) {
    const msg = String(e?.response?.data?.message || e?.response?.data?.detail || e?.message || '停止失败')
    await ElMessageBox.alert(msg, '停止失败', { type: 'error', confirmButtonText: '确定' })
  } finally {
    stopCompletedSaving.value = false
  }
}

async function handleSyncSavepathSnapshots() {
  try {
    await ElMessageBox.confirm(
      '将遍历追剧任务并刷新所有任务的保存路径快照（task_savepath_snapshots），可能耗时较久，是否继续？',
      '同步保存路径快照',
      { type: 'warning', confirmButtonText: '继续', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  syncSnapshotsSaving.value = true
  try {
    const res: any = await syncDramaSavepathSnapshots()
    const checked = Number(res?.checked || 0)
    const synced = Number(res?.synced || 0)
    const skipped = Number(res?.skipped || 0)
    const failed = Number(res?.failed || 0)
    await ElMessageBox.alert(`同步完成：checked=${checked}，synced=${synced}，skipped=${skipped}，failed=${failed}`, '同步结果', {
      type: 'success',
      confirmButtonText: '确定',
    })
    await loadData()
  } catch (e: any) {
    const msg = String(e?.response?.data?.message || e?.response?.data?.detail || e?.message || '同步失败')
    await ElMessageBox.alert(msg, '同步失败', { type: 'error', confirmButtonText: '确定' })
  } finally {
    syncSnapshotsSaving.value = false
  }
}

onMounted(() => {
  loadData()
  window.addEventListener('resize', onResize, { passive: true })
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
})
</script>

<template>
  <div class="shell-page" v-loading="loading">
    <div class="section-header">
      <div class="section-header__title">
        <h2>追剧任务</h2>
      </div>
      <div class="toolbar__right">
        <el-button type="primary" @click="loadData">刷新</el-button>
        <el-button v-if="canWrite" :loading="syncSnapshotsSaving" @click="handleSyncSavepathSnapshots">同步保存快照</el-button>
        <el-button v-if="canRun" :loading="runAllDialog.running" :disabled="runAllDialog.running" @click="confirmRunAll">执行全部</el-button>
        <el-button v-if="canWrite" :loading="stopCompletedSaving" @click="confirmStopCompleted">停止已完结任务</el-button>
        <el-button v-if="canWrite" :loading="repairSaving" @click="confirmRepairBanned">修复失效任务</el-button>
        <el-button v-if="canWrite" type="success" @click="openCreateDrawer">新增任务</el-button>
      </div>
    </div>

    <section v-if="scheduler" class="glass-panel dashboard-section" style="margin-bottom: 18px">
      <div class="dashboard-section__title">全局调度</div>
      <div class="toolbar">
        <div class="toolbar__left">
          <el-switch v-model="scheduler.enabled" active-text="启用调度" inactive-text="暂停调度" />
          <el-input v-model="scheduler.crontab" placeholder="*/15 * * * *" :style="{ width: isMobile ? '100%' : '220px' }" />
          <el-input v-model="scheduler.timezone" placeholder="Asia/Shanghai" :style="{ width: isMobile ? '100%' : '180px' }" />
        </div>
        <div class="toolbar__right">
          <el-button type="primary" :loading="schedulerSaving" @click="saveScheduler">保存调度</el-button>
        </div>
      </div>
    </section>

    <section class="glass-panel filter-strip">
      <div class="toolbar">
        <div class="toolbar__left">
          <el-input v-model="filters.keyword" clearable placeholder="搜索任务名 / 链接 / 路径" :style="{ width: isMobile ? '100%' : '260px' }" />
          <el-segmented
            v-model="filters.status"
            :options="[
              { label: '全部', value: 'all' },
              { label: '启用', value: 'enabled' },
              { label: '禁用', value: 'disabled' },
            ]"
          />
        </div>
      </div>
    </section>

    <section class="glass-panel dashboard-section">
      <el-table v-if="!isMobile" :data="filteredTasks" style="width: 100%" row-key="id">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div style="padding: 12px 18px">
              <div style="font-weight: 600; margin-bottom: 8px">最近执行</div>
              <div v-if="row.executions?.length" class="task-exec">
                <div v-for="exec in row.executions.slice(0, 3)" :key="exec.id" class="task-exec__item">
                  <div class="task-exec__meta">
                    <span class="task-exec__status">{{ exec.status }}</span>
                    <span class="task-exec__time">{{ exec.started_at }}</span>
                    <span class="task-exec__msg">{{ exec.message }}</span>
                  </div>
                  <pre v-if="exec.tree_summary" class="task-exec__tree">{{ exec.tree_summary }}</pre>
                </div>
              </div>
              <div v-else class="empty-copy">暂无执行记录。</div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="任务名" min-width="160">
          <template #default="{ row }">
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap">
              <span>{{ row.taskname }}</span>
              <el-tag v-if="row.shareurl_ban" type="danger" effect="plain">封禁</el-tag>
            </div>
            <div v-if="row.shareurl_ban" style="margin-top: 4px; font-size: 12px; color: var(--el-text-color-secondary)">
              {{ row.shareurl_ban }}
            </div>
          </template>
        </el-table-column>
        <el-table-column label="账号" width="160">
          <template #default="{ row }">
            <span>{{ formatAccountLabel(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="savepath" label="保存路径" min-width="200" />
        <el-table-column label="更新进度" width="120">
          <template #default="{ row }">
            <span v-if="!(row.tmdb_id && row.tmdb_media_type === 'tv')">-</span>
            <el-tooltip v-else effect="dark" placement="top">
              <template #content>
                <div>
                  <div>已存：{{ progressTooltip(row)?.saved }}</div>
                  <div>最新：{{ progressTooltip(row)?.latest }}</div>
                  <div>快照：{{ progressTooltip(row)?.snapshot }}</div>
                  <div v-if="progressTooltip(row)?.reason">原因：{{ progressTooltip(row)?.reason }}</div>
                </div>
              </template>
              <el-tag :type="progressTagType(row)" effect="plain">{{ progressTagText(row) }}</el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="完结" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.tmdb_media_type === 'tv' && row.tmdb_is_ended === true" type="success" effect="plain">完结</el-tag>
            <el-tag v-else-if="row.tmdb_media_type === 'tv' && row.tmdb_status" type="warning" effect="plain">连载</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="enabled" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'primary' : 'danger'">{{ row.enabled ? '启用' : '禁用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" :width="isPad ? 240 : 320" fixed="right">
          <template #default="{ row }">
            <div v-if="showAllActions" class="task-actions">
              <el-button v-if="canWrite" :type="row.enabled ? 'danger' : 'primary'" text bg  @click="handleToggle(row, !row.enabled)">{{ row.enabled ? '禁用' : '启用' }}</el-button>
              <el-button
                v-if="canRun"
                text
                bg
                type="success"
                :disabled="Boolean(row.shareurl_ban)"
                @click="handleRun(row)"
              >
                执行
              </el-button>
              <el-button v-if="canWrite" text bg  @click="openEditDrawer(row)">编辑</el-button>
              <el-button v-if="canWrite" text bg type="danger"  @click="openDeleteDialog(row)">删除</el-button>
            </div>
            <div v-else class="task-actions">
              <el-button v-if="canWrite" text bg :type="row.enabled ? 'danger' : 'primary'"  @click="handleToggle(row, !row.enabled)">{{ row.enabled ? '禁用' : '启用' }}</el-button>
              <el-button
                v-if="canRun"
                text
                bg
                type="success"
                :disabled="Boolean(row.shareurl_ban)"
                @click="handleRun(row)"
              >
                执行
              </el-button>
              <el-dropdown v-if="canWrite" trigger="click" @command="(cmd: string) => handleRowCommand(cmd, row)">
                <el-button text bg >更多</el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="edit">编辑</el-dropdown-item>
                    <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <div v-else class="task-card-list">
        <el-card v-for="row in filteredTasks" :key="row.id" class="task-card" shadow="never">
          <div class="task-card__header">
            <div class="task-card__title">
              <span>{{ row.taskname }}</span>
              <el-tag v-if="row.shareurl_ban" type="danger" effect="plain" style="margin-left: 8px">封禁</el-tag>
            </div>
            <el-tag :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '启用' : '禁用' }}</el-tag>
          </div>
          <div class="task-card__meta">
            <div class="task-card__meta-row"><span class="task-card__label">账号</span>{{ formatAccountLabel(row) }}</div>
            <div class="task-card__meta-row"><span class="task-card__label">路径</span>{{ row.savepath || '-' }}</div>
            <div class="task-card__meta-row">
              <span class="task-card__label">进度</span>
              <span v-if="!(row.tmdb_id && row.tmdb_media_type === 'tv')">-</span>
              <el-tooltip v-else effect="dark" placement="top">
                <template #content>
                  <div>
                    <div>已存：{{ progressTooltip(row)?.saved }}</div>
                    <div>最新：{{ progressTooltip(row)?.latest }}</div>
                    <div>快照：{{ progressTooltip(row)?.snapshot }}</div>
                    <div v-if="progressTooltip(row)?.reason">原因：{{ progressTooltip(row)?.reason }}</div>
                  </div>
                </template>
                <el-tag :type="progressTagType(row)" effect="plain">{{ progressTagText(row) }}</el-tag>
              </el-tooltip>
            </div>
            <div class="task-card__meta-row">
              <span class="task-card__label">完结</span>
              <span v-if="row.tmdb_media_type === 'tv' && row.tmdb_is_ended === true">完结</span>
              <span v-else-if="row.tmdb_media_type === 'tv' && row.tmdb_status">连载</span>
              <span v-else>-</span>
            </div>
            <div v-if="row.shareurl_ban" class="task-card__meta-row">
              <span class="task-card__label">封禁</span>{{ row.shareurl_ban }}
            </div>
          </div>
          <div v-if="row.executions?.length" class="task-card__exec">
            <div class="task-card__exec-title">最近执行</div>
            <div class="task-card__exec-row">
              <span class="task-card__exec-status">{{ row.executions[0].status }}</span>
              <span class="task-card__exec-time">{{ row.executions[0].started_at }}</span>
            </div>
            <div class="task-card__exec-msg">{{ row.executions[0].message }}</div>
          </div>
          <div class="task-card__actions">
            <div class="task-actions">
              <el-button v-if="canWrite" text bg :type="row.enabled ? 'danger' : 'primary'" @click="handleToggle(row, !row.enabled)">{{ row.enabled ? '禁用' : '启用' }}</el-button>
              <el-button
                v-if="canRun"
                text
                bg
                type="success"
                :disabled="Boolean(row.shareurl_ban)"
                @click="handleRun(row)"
              >
                执行
              </el-button>
              <el-button v-if="canWrite" text bg  @click="openEditDrawer(row)">编辑</el-button>
              <el-button v-if="canWrite" text bg type="danger" @click="openDeleteDialog(row)">删除</el-button>
            </div>
          </div>
        </el-card>
      </div>
    </section>

    <DramaTaskDrawer
      v-model="drawerVisible"
      :task="currentTask"
      :accounts="accounts"
      :plugins="activePlugins"
      :submitting="submitting"
      @save="submitTask"
      @run-once="handleRunOnce"
    />

    <el-dialog
      v-model="deleteDialog.visible"
      title="删除任务"
      :width="isMobile ? '92vw' : '520px'"
      :close-on-click-modal="false"
      :close-on-press-escape="!deleteDialog.loading"
      :show-close="!deleteDialog.loading"
      @close="closeDeleteDialog"
    >
      <div style="font-size: 14px; line-height: 1.6">
        <div>
          确认删除任务 <span style="font-weight: 600">{{ deleteDialog.task?.taskname || '' }}</span> 吗？
        </div>
        <div style="margin-top: 6px; color: var(--el-text-color-secondary)">
          删除后不可恢复，执行记录也会一并删除。
        </div>
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 10px">
          <el-button :disabled="deleteDialog.loading" @click="closeDeleteDialog">取消</el-button>
          <el-button type="danger" :loading="deleteDialog.loading" @click="confirmDelete">删除</el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog v-model="runLogDialog.visible" :title="runLogDialog.title" :width="isMobile ? '96vw' : '1100px'" :fullscreen="isMobile">
      <div style="display: flex; gap: 10px; align-items: center; margin-bottom: 10px">
        <el-tag v-if="runLogDialog.status" :type="runLogDialog.status === 'success' ? 'success' : runLogDialog.status === 'running' ? 'warning' : runLogDialog.status === 'skipped' ? 'info' : 'danger'">
          {{ runLogDialog.status }}
        </el-tag>
        <el-tag v-if="runLogDialog.stage" type="warning">阶段：{{ runLogDialog.stage }}</el-tag>
        <el-button style="margin-left: auto" @click="stopRunLogStream">停止读取</el-button>
        <el-button @click="copyRunLog">复制日志</el-button>
      </div>
      <pre ref="runLogPre" style="white-space: pre-wrap; font-size: 12px; line-height: 1.5; background: var(--el-fill-color-blank); border: 1px solid var(--el-border-color-lighter); border-radius: 16px; padding: 12px; max-height: 65vh; overflow: auto">{{ runLogDialog.content }}</pre>
    </el-dialog>

    <el-dialog v-model="runAllDialog.visible" :title="runAllDialog.title" :width="isMobile ? '96vw' : '1100px'" :fullscreen="isMobile">
      <div style="display: flex; gap: 10px; align-items: center; margin-bottom: 10px; flex-wrap: wrap">
        <el-tag :type="runAllDialog.running ? 'warning' : 'success'">{{ runAllDialog.running ? 'running' : 'done' }}</el-tag>
        <el-tag v-if="runAllStats.success" type="success">success：{{ runAllStats.success }}</el-tag>
        <el-tag v-if="runAllStats.failed" type="danger">failed：{{ runAllStats.failed }}</el-tag>
        <el-tag v-if="runAllStats.skipped" type="info">skipped：{{ runAllStats.skipped }}</el-tag>
        <el-tag v-if="runAllStats.aborted" type="warning">aborted：{{ runAllStats.aborted }}</el-tag>
        <el-tag v-if="runAllStats.pending" type="info">pending：{{ runAllStats.pending }}</el-tag>
        <el-tag v-if="runAllStats.unknown" type="danger">unknown：{{ runAllStats.unknown }}</el-tag>
        <el-button style="margin-left: auto" :disabled="!runAllDialog.running" @click="stopRunAllStream">停止全部</el-button>
        <el-button :disabled="!runAllDialog.items.length" @click="copyRunAllLog">复制全部日志</el-button>
      </div>

      <el-collapse v-model="runAllDialog.activeNames">
        <el-collapse-item v-for="item in runAllDialog.items" :key="item.taskId" :name="item.taskId">
          <template #title>
            <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap">
              <el-tag
                v-if="item.status"
                :type="
                  item.status === 'success'
                    ? 'success'
                    : item.status === 'running'
                      ? 'warning'
                      : item.status === 'skipped'
                        ? 'info'
                        : item.status === 'pending'
                          ? 'info'
                          : item.status === 'aborted'
                            ? 'warning'
                            : 'danger'
                "
              >
                {{ item.status }}
              </el-tag>
              <span style="font-weight: 600">{{ item.taskname }}</span>
              <span v-if="item.stage" style="font-size: 12px; color: var(--el-text-color-secondary)">阶段：{{ item.stage }}</span>
              <span v-if="item.message" style="font-size: 12px; color: var(--el-text-color-secondary)">{{ item.message }}</span>
            </div>
          </template>
          <pre :ref="setRunAllPreRef(item.taskId)" class="run-all-pre">{{ item.content }}</pre>
        </el-collapse-item>
      </el-collapse>
    </el-dialog>
  </div>
</template>

<style scoped>
.task-exec {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.task-exec__item {
  padding: 12px;
  border-radius: 16px;
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
}

.task-exec__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.task-exec__status {
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.task-exec__tree {
  margin: 10px 0 0;
  white-space: pre-wrap;
  font-size: 12px;
  color: var(--el-text-color-primary);
}

.task-card-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.task-card {
  border-radius: 18px;
  border: 1px solid var(--el-border-color-lighter);
  background: var(--el-fill-color-blank);
}

.task-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.task-card__title {
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.task-card__meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.task-card__meta-row {
  display: flex;
  gap: 10px;
  align-items: baseline;
}

.run-all-pre {
  white-space: pre-wrap;
  font-size: 12px;
  line-height: 1.5;
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 16px;
  padding: 12px;
  max-height: 45vh;
  overflow: auto;
}

.task-card__label {
  width: 36px;
  color: var(--el-text-color-primary);
  font-weight: 600;
}

.task-card__exec {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--el-border-color);
}

.task-card__exec-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin-bottom: 6px;
}

.task-card__exec-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.task-card__exec-status {
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.task-card__exec-msg {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.task-card__actions {
  margin-top: 12px;
}

.task-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
}

.task-actions__first {
  margin-right: 14px;
}

.task-actions__item {
  margin-right: 6px;
}

.task-actions__last {
  margin-right: 0;
}

@media (max-width: 768px) {
  .section-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }

  .toolbar__right {
    width: 100%;
    justify-content: flex-start;
    flex-wrap: wrap;
    gap: 10px;
  }

  .toolbar__left {
    width: 100%;
    flex-wrap: wrap;
    gap: 10px;
  }
}
</style>
