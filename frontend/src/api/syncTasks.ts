import { http } from '@/api/http'
import type { PathBrowseResponse } from '@/types/pathBrowse'
import type { SyncExecutionItem, SyncTaskItem } from '@/types/syncTasks'

export async function fetchSyncTasks() {
  const { data } = await http.get<SyncTaskItem[]>('/sync-tasks')
  return data
}

export async function createSyncTask(payload: {
  name: string
  enabled: boolean
  source: { type: string; path: string }
  target: { type: string; path: string }
  mode: string
  strategy: Record<string, any>
  drama_task_uids?: string[]
}) {
  const { data } = await http.post<SyncTaskItem>('/sync-tasks', payload, { headers: { 'X-Silent-Toast': '1' } })
  return data
}

export async function updateSyncTask(
  syncTaskId: number,
  payload: Partial<{
    name: string
    enabled: boolean
    source: { type: string; path: string }
    target: { type: string; path: string }
    mode: string
    strategy: Record<string, any>
    drama_task_uids: string[]
  }>,
) {
  const { data } = await http.patch<SyncTaskItem>(`/sync-tasks/${syncTaskId}`, payload, { headers: { 'X-Silent-Toast': '1' } })
  return data
}

export async function deleteSyncTask(syncTaskId: number) {
  const { data } = await http.delete<{ ok: boolean }>(`/sync-tasks/${syncTaskId}`)
  return data
}

export async function fetchSyncExecutions(syncTaskId: number) {
  const { data } = await http.get<SyncExecutionItem[]>(`/sync-tasks/${syncTaskId}/executions`)
  return data
}

export async function fetchSyncExecutionLatest(syncTaskId: number) {
  const { data } = await http.get<SyncExecutionItem | null>(`/sync-tasks/${syncTaskId}/executions/latest`)
  return data
}

export async function fetchSyncExecutionFiles(syncTaskId: number, executionId: number, payload?: { offset?: number; limit?: number }) {
  const offset = Number(payload?.offset || 0) || 0
  const limit = Number(payload?.limit || 500) || 500
  const { data } = await http.get<any[]>(`/sync-tasks/${syncTaskId}/executions/${executionId}/files`, { params: { offset, limit } })
  return data
}

export async function runSyncTask(syncTaskId: number, payload?: { strategy?: Record<string, any> } | null) {
  const { data } = await http.post<SyncExecutionItem>(`/sync-tasks/${syncTaskId}/run`, payload || {})
  return data
}

export async function browseLocalSync(payload: { path: string; max_items?: number }) {
  const { data } = await http.post<PathBrowseResponse>('/sync-tasks/local/browse', payload)
  return data
}
