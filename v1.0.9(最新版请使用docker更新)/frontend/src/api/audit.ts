import { http } from '@/api/http'
import type { AuditLogListResponse } from '@/types/audit'

export async function fetchAuditLogs(params: {
  page: number
  page_size: number
  q?: string
  action?: string
  success?: boolean
}) {
  const { data } = await http.get<AuditLogListResponse>('/audit-logs', { params })
  return data
}

