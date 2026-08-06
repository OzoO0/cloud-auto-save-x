import { http } from '@/api/http'
import type {
  CacheClearOut,
  CacheDeleteOut,
  CachePurgeOut,
  InvalidShareLinkClearIn,
  InvalidShareLinkListOut,
  SharePreviewBatchCacheListOut,
  SharePreviewBatchCachePurgeIn,
} from '@/types/shareLinkCache'

export async function fetchSharePreviewBatchCacheList(params: {
  page: number
  page_size: number
  q?: string
  drive_type?: string
  ok?: boolean
  expired_only?: boolean
}) {
  const response = await http.get<SharePreviewBatchCacheListOut>('/cache/share-preview-batch/list', { params })
  return response.data
}

export async function deleteSharePreviewBatchCacheItem(params: { shareurl: string }) {
  const response = await http.delete<CacheDeleteOut>('/cache/share-preview-batch/item', { params })
  return response.data
}

export async function purgeSharePreviewBatchCache(payload: SharePreviewBatchCachePurgeIn) {
  const response = await http.post<CachePurgeOut>('/cache/share-preview-batch/purge', payload)
  return response.data
}

export async function clearSharePreviewBatchMemoryCache() {
  const response = await http.post<CacheClearOut>('/cache/share-preview-batch/clear-memory')
  return response.data
}

export async function fetchInvalidShareLinksList(params: { page: number; page_size: number; q?: string; drive_type?: string }) {
  const response = await http.get<InvalidShareLinkListOut>('/cache/invalid-share-links/list', { params })
  return response.data
}

export async function deleteInvalidShareLink(params: { shareurl: string }) {
  const response = await http.delete<CacheDeleteOut>('/cache/invalid-share-links/item', { params })
  return response.data
}

export async function clearInvalidShareLinks(payload: InvalidShareLinkClearIn) {
  const response = await http.post<CachePurgeOut>('/cache/invalid-share-links/clear', payload)
  return response.data
}
