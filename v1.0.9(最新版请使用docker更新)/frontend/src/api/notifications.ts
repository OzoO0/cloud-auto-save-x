import { http } from '@/api/http'
import type { NotificationConfig, NotificationTestResult } from '@/types/notifications'

export async function fetchNotificationConfig() {
  const response = await http.get<NotificationConfig>('/notifications/config')
  return response.data
}

export async function updateNotificationConfig(payload: { enabled?: boolean; config?: Record<string, any> }) {
  const response = await http.patch<NotificationConfig>('/notifications/config', payload)
  return response.data
}

export async function sendNotificationTest(payload: { title: string; content: string; channels?: string[] }) {
  const response = await http.post<NotificationTestResult>('/notifications/test', payload)
  return response.data
}
