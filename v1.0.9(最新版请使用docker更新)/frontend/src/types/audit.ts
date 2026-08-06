export type AuditLogItem = {
  id: number
  actor_user_id?: number | null
  actor_username?: string | null
  action: string
  target_type?: string | null
  target_id?: string | null
  ip?: string | null
  user_agent?: string | null
  success: boolean
  detail?: string | null
  created_at: string
}

export type AuditLogListResponse = {
  page: number
  page_size: number
  total: number
  items: AuditLogItem[]
}

