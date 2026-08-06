import type { DriveAccountItem } from '@/types/extensions'

export type CapacitySummary = {
  account_count: number
  enabled_account_count: number
  capacity_account_count: number
  warning_account_count: number
  total_used_space?: number | null
  total_space?: number | null
  usage_ratio?: number | null
}

export type CapacityOverview = {
  summary: CapacitySummary
  accounts: DriveAccountItem[]
  warning_accounts: DriveAccountItem[]
  unsupported_accounts: DriveAccountItem[]
  updated_at?: string | null
}

export type DramaSummary = {
  task_count: number
  enabled_task_count: number
  tmdb_bound_count: number
  banned_count: number
  unknown_schedule_count: number
  monthly_success_count: number
  window_days: number
  execution_total: number
  execution_success: number
  execution_failed: number
  execution_skipped: number
  success_rate?: number | null
  avg_duration_s?: number | null
}

export type DramaTrendPoint = {
  date: string
  total: number
  success: number
  failed: number
  skipped: number
  avg_duration_s?: number | null
}

export type DramaFailureItem = {
  task_id: number
  taskname: string
  status: string
  started_at: string
  stage?: string | null
  message?: string | null
}

export type DramaOverview = {
  scheduler: {
    enabled: boolean
    crontab: string
    timezone: string
  }
  summary: DramaSummary
  trend: DramaTrendPoint[]
  recent_failures: DramaFailureItem[]
  updated_at?: string | null
}
