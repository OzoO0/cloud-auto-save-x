export type TaskExtraConfig = Record<string, any> & {
  auto_update_115_shareurl?: boolean | null
}

export type TaskExecutionItem = {
  id: number
  task_id: number
  status: string
  started_at: string
  finished_at?: string | null
  tree_summary?: string | null
  message?: string | null
  stage?: string | null
  run_log?: string | null
  adapter_snapshot: Record<string, any>
  plugins_snapshot: Array<Record<string, any>>
}

export type TaskItem = {
  id: number
  task_uid: string
  task_type: string
  taskname: string
  shareurl: string
  savepath: string
  pattern?: string | null
  replace?: string | null
  enddate?: string | null
  ignore_extension: boolean
  sort_index?: number | null
  startfid?: string | null
  account_name?: string | null
  update_subdir?: string | null
  shareurl_ban?: string | null
  tmdb_id?: number | null
  tmdb_media_type?: string | null
  tmdb_status?: string | null
  tmdb_is_ended?: boolean | null
  drama_update_progress?: {
    available: boolean
    tmdb_season?: number | null
    tmdb_episode?: number | null
    saved_season?: number | null
    saved_episode?: number | null
    behind_episodes?: number | null
    is_latest?: boolean | null
    snapshot_captured_at?: string | null
    reason?: string | null
  } | null
  enabled: boolean
  addition: Record<string, any>
  extra: TaskExtraConfig
  created_at: string
  updated_at: string
  executions?: TaskExecutionItem[]
}

export type TaskSchedulerSetting = {
  enabled: boolean
  crontab: string
  timezone: string
}

export type StopCompletedDramaTasksResponse = {
  checked: number
  matched: number
  stopped: number
  task_ids: number[]
}

export type SharePreviewItem = {
  fid: string
  fid_token?: string | null
  name: string
  name_re?: string | null
  is_dir: boolean
  updated_at?: any | null
  size?: number | null
  children_count?: number | null
  file_name?: string | null
  file_name_re?: string | null
  file_name_saved?: string | null
  dir?: boolean | null
  include_items?: number | null
}

export type SharePreviewResponse = {
  drive_type: string
  suggested_account_name?: string | null
  pwd_id?: string | null
  pdir_fid?: string | null
  items: SharePreviewItem[]
}

export type SharePreviewBatchItem = {
  shareurl: string
  drive_type?: string | null
  ok: boolean
  message?: string | null
  suggested_account_name?: string | null
  pdir_fid?: string | null
  resolved_pdir_fid?: string | null
  latest_video?: {
    fid?: string | null
    name?: string | null
    updated_at?: any | null
    size?: number | null
    season?: number | null
    episode?: number | null
  } | null
}

export type SharePreviewBatchResponse = {
  items: SharePreviewBatchItem[]
}

export type RepairBannedTaskItem = {
  task_id: number
  taskname: string
  drive_type?: string | null
  old_shareurl?: string | null
  new_shareurl?: string | null
  season?: number | null
  episode?: number | null
  size?: number | null
}

export type RepairBannedTasksResponse = {
  checked: number
  repaired: number
  items: RepairBannedTaskItem[]
}

export type DriveBrowseItem = {
  fid: string
  name: string
  is_dir: boolean
  updated_at?: any | null
  size?: number | null
  include_items?: number | null
  file_name?: string | null
  dir?: boolean | null
}

export type DriveBrowsePath = {
  fid: string
  name: string
}

export type DriveBrowseResponse = {
  account_name: string
  drive_type?: string | null
  dir_path: string
  exists: boolean
  pdir_fid?: string | null
  items: DriveBrowseItem[]
  paths?: DriveBrowsePath[]
}

export type MagicRegexRule = {
  key: string
  label?: string | null
  pattern: string
  replace: string
}

export type MagicRegexResponse = {
  rules: MagicRegexRule[]
}
