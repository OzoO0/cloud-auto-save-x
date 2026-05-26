import { http } from '@/api/http'
import type {
  DriveBrowseResponse,
  MagicRegexResponse,
  RepairBannedTasksResponse,
  SharePreviewBatchResponse,
  SharePreviewResponse,
  StopCompletedDramaTasksResponse,
  TaskExecutionItem,
  TaskItem,
  TaskSchedulerSetting,
} from '@/types/tasks'
import { detectDriveTypeByUrl } from '@/utils/driveType'

export async function fetchTasks() {
  const { data } = await http.get<TaskItem[]>('/tasks')
  return data
}

export async function syncDramaSavepathSnapshots() {
  const { data } = await http.post('/tasks/drama/savepath-snapshots/sync')
  return data
}

export async function createTask(payload: {
  task_uid?: string | null
  task_type: string
  taskname: string
  shareurl: string
  savepath: string
  pattern?: string | null
  replace?: string | null
  enddate?: string | null
  ignore_extension?: boolean
  sort_index?: number | null
  startfid?: string | null
  account_name?: string | null
  update_subdir?: string | null
  tmdb_id?: number | null
  tmdb_media_type?: string | null
  enabled?: boolean
  addition?: Record<string, any>
  extra?: Record<string, any>
}) {
  const { data } = await http.post<TaskItem>('/tasks', payload, { headers: { 'X-Silent-Toast': '1' } })
  return data
}

export async function updateTask(
  taskId: number,
  payload: Partial<{
    task_type: string
    taskname: string
    shareurl: string
    savepath: string
    pattern: string | null
    replace: string | null
    enddate: string | null
    ignore_extension: boolean
    sort_index: number | null
    startfid: string | null
    account_name: string | null
    update_subdir: string | null
    tmdb_id: number | null
    tmdb_media_type: string | null
    enabled: boolean
    addition: Record<string, any>
    extra: Record<string, any>
  }>,
) {
  const { data } = await http.patch<TaskItem>(`/tasks/${taskId}`, payload, { headers: { 'X-Silent-Toast': '1' } })
  return data
}

export async function setTaskStatus(taskId: number, enabled: boolean) {
  const { data } = await http.patch<TaskItem>(`/tasks/${taskId}/status`, { enabled })
  return data
}

export async function runTask(taskId: number) {
  const { data } = await http.post<TaskExecutionItem>(`/tasks/${taskId}/run`)
  return data
}

export async function deleteTask(taskId: number) {
  const { data } = await http.delete<{ ok: boolean }>(`/tasks/${taskId}`)
  return data
}

export async function fetchTaskSchedulerSetting() {
  const { data } = await http.get<TaskSchedulerSetting>('/tasks/scheduler')
  return data
}

export async function fetchMagicRegex() {
  const { data } = await http.get<MagicRegexResponse>('/tasks/magic-regex')
  return data
}

export async function updateTaskSchedulerSetting(payload: Partial<TaskSchedulerSetting>) {
  const { data } = await http.patch<TaskSchedulerSetting>('/tasks/scheduler', payload)
  return data
}

export async function previewShare(payload: {
  shareurl: string
  account_name?: string | null
  pdir_fid?: string | null
  max_items?: number
  taskname?: string
  pattern?: string | null
  replace?: string | null
  sort_index?: number | null
  savepath?: string | null
  ignore_extension?: boolean | null
  update_subdir?: string | null
  startfid?: string | null
  tmdb_id?: number | null
  tmdb_media_type?: string | null
}) {
  const { data } = await http.post<SharePreviewResponse>('/tasks/share/preview', payload)
  return data
}

export async function previewShareBatch(payload: { shareurls: string[]; account_name?: string | null }) {
  const accountName = payload.account_name ?? null
  const shareurls = (payload.shareurls || []).map((x) => String(x || '').trim()).filter(Boolean)
  if (!shareurls.length) return { items: [] }
  const limit = 50

  const postOnce = async (batch: string[]) => {
    const { data } = await http.post<SharePreviewBatchResponse>(
      '/tasks/share/preview-batch',
      { shareurls: batch, account_name: accountName },
      { headers: { 'X-Retryable': '1' } },
    )
    return data
  }

  const chunk = <T,>(items: T[], size: number) => {
    const out: T[][] = []
    for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size))
    return out
  }

  const mergeByInputOrder = (items: SharePreviewBatchResponse['items']) => {
    const mapping = new Map<string, (typeof items)[number]>()
    for (const it of items || []) {
      const url = String((it as any)?.shareurl || '').trim()
      if (!url || mapping.has(url)) continue
      mapping.set(url, it)
    }
    const ordered: (typeof items)[number][] = []
    for (const url of shareurls) {
      const it = mapping.get(url)
      if (it) ordered.push(it)
    }
    return ordered
  }

  if (shareurls.length <= limit) {
    const out = await postOnce(shareurls)
    return { items: mergeByInputOrder(out.items || []) }
  }

  if (accountName) {
    const merged: SharePreviewBatchResponse['items'] = []
    for (const part of chunk(shareurls, limit)) {
      const out = await postOnce(part)
      merged.push(...(out.items || []))
    }
    return { items: mergeByInputOrder(merged) }
  }

  const groups = new Map<string, string[]>()
  for (const url of shareurls) {
    const dt = detectDriveTypeByUrl(url) || 'unknown'
    const list = groups.get(dt) || []
    list.push(url)
    groups.set(dt, list)
  }

  const all = await Promise.all(
    [...groups.values()].map(async (urls) => {
      const merged: SharePreviewBatchResponse['items'] = []
      for (const part of chunk(urls, limit)) {
        const out = await postOnce(part)
        merged.push(...(out.items || []))
      }
      return merged
    }),
  )

  return { items: mergeByInputOrder(all.flat()) }
}

export async function browseDrive(payload: { dir_path: string; account_name?: string | null; shareurl?: string | null; max_items?: number }) {
  const { data } = await http.post<DriveBrowseResponse>('/tasks/drive/browse', payload)
  return data
}

export async function mkdirDrive(payload: { dir_path: string; account_name?: string | null; shareurl?: string | null }) {
  const { data } = await http.post<{ account_name: string; dir_path: string; response: Record<string, any> }>('/tasks/drive/mkdir', payload)
  return data
}

export async function repairBannedDramaTasks() {
  const { data } = await http.post<RepairBannedTasksResponse>('/tasks/repair-banned', null, { headers: { 'X-Silent-Toast': '1' } })
  return data
}

export async function stopCompletedDramaTasks() {
  const { data } = await http.post<StopCompletedDramaTasksResponse>('/tasks/drama/stop-completed', null, {
    headers: { 'X-Silent-Toast': '1' },
  })
  return data
}
