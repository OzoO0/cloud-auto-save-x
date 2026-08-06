import { http } from '@/api/http'
import type { ProxyImageCacheOperateOut, ProxyImageCacheStats } from '@/types/proxyImageCache'

export async function fetchProxyImageCacheStats() {
  const response = await http.get<ProxyImageCacheStats>('/cache/proxy-image/stats')
  return response.data
}

export async function purgeProxyImageCache() {
  const response = await http.post<ProxyImageCacheOperateOut>('/cache/proxy-image/purge')
  return response.data
}

export async function clearProxyImageCache() {
  const response = await http.post<ProxyImageCacheOperateOut>('/cache/proxy-image/clear')
  return response.data
}
