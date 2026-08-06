import { http } from '@/api/http'
import type { TMDBCacheItem, TMDBCacheListOut, TMDBCacheSchedulerSetting, TMDBCacheStatus } from '@/types/tmdbCache'

export async function fetchTMDBCacheScheduler() {
  const response = await http.get<TMDBCacheSchedulerSetting>('/tmdb/cache/scheduler')
  return response.data
}

export async function patchTMDBCacheScheduler(payload: Partial<TMDBCacheSchedulerSetting>) {
  const response = await http.patch<TMDBCacheSchedulerSetting>('/tmdb/cache/scheduler', payload)
  return response.data
}

export async function fetchTMDBCacheStatus(params: { media_type: string; tmdb_id: number }) {
  const response = await http.get<TMDBCacheStatus>('/tmdb/cache/status', { params })
  return response.data
}

export async function fetchTMDBCacheItem(params: { media_type: string; tmdb_id: number }) {
  const response = await http.get<TMDBCacheItem>('/tmdb/cache/item', { params })
  return response.data
}

export async function fetchTMDBCacheList(params: {
  page: number
  page_size: number
  media_type?: string
  q?: string
  status?: string
  expired_only?: boolean
}) {
  const response = await http.get<TMDBCacheListOut>('/tmdb/cache/list', { params })
  return response.data
}

export async function refreshTMDBCache(payload: { media_type: string; tmdb_id: number; force?: boolean; async_refresh?: boolean }) {
  const response = await http.post<{ queued: boolean; status: TMDBCacheStatus }>('/tmdb/cache/refresh', payload)
  return response.data
}

export async function refreshLinkedTasks(payload: { enabled_only?: boolean; max_items?: number; force?: boolean }) {
  const response = await http.post<{ configured: boolean; targets: number; refreshed: number }>('/tmdb/cache/refresh-linked-tasks', payload)
  return response.data
}

export async function purgeTMDBCache(payload: { retention_days: number }) {
  const response = await http.post<{ deleted: number }>('/tmdb/cache/purge', payload)
  return response.data
}

export async function setTMDBCacheTTL(payload: { media_type: string; tmdb_id: number; ttl_seconds: number }) {
  const response = await http.post<{ updated: boolean; status: TMDBCacheStatus }>('/tmdb/cache/set-ttl', payload)
  return response.data
}

export async function deleteTMDBCacheItem(params: { media_type: string; tmdb_id: number }) {
  const response = await http.delete<{ deleted: number }>('/tmdb/cache/item', { params })
  return response.data
}
