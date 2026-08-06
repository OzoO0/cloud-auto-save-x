export interface CacheDeleteOut {
  deleted: number
}

export interface CachePurgeOut {
  deleted: number
}

export interface CacheClearOut {
  cleared: boolean
}

export interface SharePreviewBatchCachePurgeIn {
  expired_only: boolean
  retention_seconds: number
}

export interface SharePreviewBatchCacheListItem {
  shareurl: string
  drive_type: string | null
  ok: boolean
  message: string | null
  checked_at: string | null
  expires_at: string | null
  hit_count: number
  updated_at: string | null
}

export interface SharePreviewBatchCacheListOut {
  page: number
  page_size: number
  total: number
  items: SharePreviewBatchCacheListItem[]
}

export interface InvalidShareLinkListItem {
  shareurl: string
  drive_type: string | null
  message: string | null
  hit_count: number
  created_at: string | null
  updated_at: string | null
}

export interface InvalidShareLinkListOut {
  page: number
  page_size: number
  total: number
  items: InvalidShareLinkListItem[]
}

export interface InvalidShareLinkClearIn {
  drive_type?: string | null
}
