export type ConfigFieldItem = {
  key: string
  label?: string
  description?: string
  input_type?: 'text' | 'textarea' | 'password' | 'switch' | 'number'
  required?: boolean
  secret?: boolean
  placeholder?: string
  default?: any
}

export type DriveTypeItem = {
  code: string
  drive_name: string
  class_name: string
  config_format: 'raw' | 'kv'
  default_config: Record<string, any>
  config_fields: ConfigFieldItem[]
}

export type DriveAccountProfile = {
  drive_type?: string
  drive_name?: string
  nickname?: string
  username?: string
  used_space?: number | null
  total_space?: number | null
  member_type?: string | null
  member_status?: string | Record<string, any> | null
  raw?: Record<string, any> | null
}

export type DriveAccountItem = {
  id: number
  name: string
  drive_type: string
  config: Record<string, any>
  profile: DriveAccountProfile
  enabled: boolean
  is_default: boolean
  capacity_warning_threshold: number
  used_space?: number | null
  total_space?: number | null
  usage_ratio?: number | null
  runtime_status?: string | null
  probe_fail_count?: number | null
  last_checked_at?: string | null
  profile_updated_at?: string | null
  last_error?: string | null
  created_at: string
  updated_at: string
}

export type PluginItem = {
  id: number
  plugin_key: string
  module_name: string
  source_type: string
  version?: string | null
  installed: boolean
  discovered_at: string
  enabled: boolean
  priority: number
  runtime_status?: string | null
  last_checked_at?: string | null
  last_error?: string | null
  config: Record<string, any>
  config_fields: ConfigFieldItem[]
  default_task_config: Record<string, any>
  task_config_fields: ConfigFieldItem[]
}
