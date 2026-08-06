export interface ProxyImageCacheStats {
  enabled: boolean
  cache_dir: string
  ttl_seconds: number
  max_file_bytes: number
  max_total_bytes: number
  total_files: number
  total_bytes: number
  stale_files: number
}

export interface ProxyImageCacheOperateOut {
  deleted_files: number
  deleted_bytes: number
}
