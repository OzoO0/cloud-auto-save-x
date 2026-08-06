import { http } from '@/api/http'
import type { DoubanCategoryList, MediaDiscoverList, TMDBDetail, TMDBSearchList } from '@/types/media'

const TMDB_DETAIL_TTL_MS = 60_000

type TMDBDetailCacheEntry = {
  data: TMDBDetail
  expiresAt: number
}

const tmdbDetailCache = new Map<string, TMDBDetailCacheEntry>()
const tmdbDetailInFlight = new Map<string, Promise<TMDBDetail>>()

function cacheKey(mediaType: 'movie' | 'tv', id: number) {
  return `${mediaType}:${id}`
}

function cloneTMDBDetail(data: TMDBDetail): TMDBDetail {
  const anyGlobal: any = globalThis as any
  if (typeof anyGlobal?.structuredClone === 'function') return anyGlobal.structuredClone(data)
  return JSON.parse(JSON.stringify(data))
}

export function invalidateTMDBDetailCache(mediaType?: 'movie' | 'tv', id?: number) {
  if (!mediaType || !id) {
    tmdbDetailCache.clear()
    tmdbDetailInFlight.clear()
    return
  }
  const key = cacheKey(mediaType, id)
  tmdbDetailCache.delete(key)
  tmdbDetailInFlight.delete(key)
}

export async function fetchDoubanCategories() {
  const response = await http.get<DoubanCategoryList>('/media/douban/categories')
  return response.data
}

export async function fetchDoubanList(params: { main_category: string; sub_category?: string; start?: number; limit?: number }) {
  const response = await http.get<MediaDiscoverList>('/media/douban/list', { params })
  return response.data
}

export async function searchTMDB(params: { q: string; type?: 'multi' | 'movie' | 'tv'; page?: number; year?: string }) {
  const response = await http.get<TMDBSearchList>('/media/search', { params })
  return response.data
}

export async function fetchTMDBDetail(mediaType: 'movie' | 'tv', id: number, opts?: { force?: boolean }) {
  const mid = Number(id) || 0
  if (mid <= 0) {
    const response = await http.get<TMDBDetail>(`/media/${mediaType}/${id}`)
    return response.data
  }

  const key = cacheKey(mediaType, mid)
  const now = Date.now()

  if (!opts?.force) {
    const cached = tmdbDetailCache.get(key)
    if (cached && cached.expiresAt > now) return cloneTMDBDetail(cached.data)
    const inflight = tmdbDetailInFlight.get(key)
    if (inflight) return cloneTMDBDetail(await inflight)
  }

  const p = (async () => {
    const response = await http.get<TMDBDetail>(`/media/${mediaType}/${mid}`)
    return response.data
  })()

  tmdbDetailInFlight.set(key, p)
  try {
    const data = await p
    tmdbDetailCache.set(key, { data, expiresAt: now + TMDB_DETAIL_TTL_MS })
    return cloneTMDBDetail(data)
  } finally {
    tmdbDetailInFlight.delete(key)
  }
}
