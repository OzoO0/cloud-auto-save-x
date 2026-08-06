export interface TMDBCacheSchedulerSetting {
  enabled: boolean
  crontab: string
  timezone: string
  max_items_per_run: number
  only_refresh_linked_tasks: boolean
  retention_days: number
}

export interface TMDBCacheStatus {
  configured: boolean
  media_type: string
  tmdb_id: number
  exists: boolean

  language?: string | null
  poster_language?: string | null

  display_title?: string | null
  original_title?: string | null
  year?: string | null
  status?: string | null

  fetched_at?: string | null
  expires_at?: string | null
  last_accessed_at?: string | null

  refresh_in_progress?: boolean
  refresh_started_at?: string | null

  fail_count?: number
  last_error?: string | null
}

export interface TMDBCacheListItem {
  media_type: string
  tmdb_id: number
  language?: string | null
  poster_language?: string | null
  display_title?: string | null
  original_title?: string | null
  year?: string | null
  status?: string | null
  fetched_at?: string | null
  expires_at?: string | null
  last_accessed_at?: string | null
  refresh_in_progress?: boolean
  fail_count?: number
  last_error?: string | null
}

export interface TMDBCacheListOut {
  configured: boolean
  page: number
  page_size: number
  total: number
  items: TMDBCacheListItem[]
}

export interface TMDBCacheItem extends TMDBCacheStatus {
  payload_json?: string | null
  update_weekdays?: number[]
}
