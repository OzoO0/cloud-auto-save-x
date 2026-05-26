export type SyncEndpointType = 'local' | 'openlist'

export type SyncMode = 'one_way' | 'two_way'

export type SyncEndpoint = {
  type: SyncEndpointType
  path: string
}

export type SyncStrategy = {
  overwrite: boolean
  one_way_delete_extras: boolean
  force_refresh: boolean
  concurrency: number
  request_interval_seconds: number
  openlist_copy_batch_size: number
}

export type SyncExecutionItem = {
  id: number
  sync_task_id: number
  status: string
  started_at: string
  finished_at?: string | null
  stage?: string | null
  run_log?: string | null
  stats: Record<string, any>
  message?: string | null
}

export type SyncTaskItem = {
  id: number
  name: string
  enabled: boolean
  source: SyncEndpoint
  target: SyncEndpoint
  mode: SyncMode
  strategy: SyncStrategy
  drama_task_uids?: string[]
  created_at: string
  updated_at: string
}
