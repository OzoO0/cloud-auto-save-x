import { http } from '@/api/http'
import type { DriveAccountItem, DriveTypeItem, PluginItem } from '@/types/extensions'

export async function fetchDriveAccounts() {
  const { data } = await http.get<DriveAccountItem[]>('/drive-accounts')
  return data
}

export async function fetchDriveTypes() {
  const { data } = await http.get<DriveTypeItem[]>('/drive-accounts/types')
  return data
}

export async function createDriveAccount(payload: {
  name: string
  drive_type: string
  cookie?: string
  config?: Record<string, any>
  enabled: boolean
  is_default: boolean
  capacity_warning_threshold?: number
}) {
  const { data } = await http.post<DriveAccountItem>('/drive-accounts', payload)
  return data
}

export async function updateDriveAccount(
  accountId: number,
  payload: Partial<{
    name: string
    cookie: string
    config: Record<string, any>
    enabled: boolean
    is_default: boolean
    capacity_warning_threshold: number
  }>,
) {
  const { data } = await http.patch<DriveAccountItem>(`/drive-accounts/${accountId}`, payload)
  return data
}

export async function setDriveAccountStatus(accountId: number, enabled: boolean) {
  const { data } = await http.patch<DriveAccountItem>(`/drive-accounts/${accountId}/status`, { enabled })
  return data
}

export async function setDriveAccountDefault(accountId: number) {
  const { data } = await http.post<DriveAccountItem>(`/drive-accounts/${accountId}/default`)
  return data
}

export async function deleteDriveAccount(accountId: number) {
  const { data } = await http.delete<{ ok: boolean }>(`/drive-accounts/${accountId}`)
  return data
}

export async function probeDriveAccount(accountId: number, options?: { silentToast?: boolean }) {
  const headers: Record<string, string> = {}
  if (options?.silentToast) headers['X-Silent-Toast'] = '1'
  const { data } = await http.post<DriveAccountItem>(`/drive-accounts/${accountId}/probe`, null, { headers })
  return data
}

export async function signInDriveAccount(accountId: number) {
  const { data } = await http.post(`/drive-accounts/${accountId}/sign-in`)
  return data as any
}

export async function startDriveAccountAuth(accountId: number) {
  const { data } = await http.post<DriveAccountItem>(`/drive-accounts/${accountId}/auth/start`, null, {
    headers: { 'X-Silent-Toast': '1' },
  })
  return data
}

export async function startDriveAccountQrcodeAuth(accountId: number) {
  const { data } = await http.post(`/drive-accounts/${accountId}/auth/qrcode/start`, null, {
    headers: { 'X-Silent-Toast': '1' },
  })
  return data as any
}

export async function pollDriveAccountQrcodeAuth(sessionId: string) {
  const { data } = await http.post<DriveAccountItem>(`/drive-accounts/auth/${sessionId}/qrcode/poll`, null, {
    headers: { 'X-Silent-Toast': '1' },
  })
  return data
}

export async function submitDriveAccountCaptcha(sessionId: string, code: string) {
  const { data } = await http.post<DriveAccountItem>(
    `/drive-accounts/auth/${sessionId}/captcha`,
    { code },
    { headers: { 'X-Silent-Toast': '1' } },
  )
  return data
}

export async function sendDriveAccountSms(sessionId: string) {
  const { data } = await http.post(`/drive-accounts/auth/${sessionId}/sms/send`, null, {
    headers: { 'X-Silent-Toast': '1' },
  })
  return data as any
}

export async function submitDriveAccountSms(sessionId: string, code: string) {
  const { data } = await http.post<DriveAccountItem>(
    `/drive-accounts/auth/${sessionId}/sms/submit`,
    { code },
    { headers: { 'X-Silent-Toast': '1' } },
  )
  return data
}

export async function fetchDriveAccountAuthSession(sessionId: string) {
  const { data } = await http.get(`/drive-accounts/auth/${sessionId}`, { headers: { 'X-Silent-Toast': '1' } })
  return data as any
}

export async function fetchDriveAccountProbeScheduler() {
  const { data } = await http.get('/drive-accounts/probe/scheduler')
  return data as any
}

export async function patchDriveAccountProbeScheduler(payload: Partial<{ enabled: boolean; crontab: string; timezone: string; enabled_only: boolean }>) {
  const { data } = await http.patch('/drive-accounts/probe/scheduler', payload)
  return data as any
}

export async function refreshDriveAccountProfiles() {
  const { data } = await http.post<DriveAccountItem[]>('/drive-accounts/refresh-profiles')
  return data
}

export async function fetchPlugins() {
  const { data } = await http.get<PluginItem[]>('/plugins')
  return data
}

export async function refreshPlugins() {
  const { data } = await http.post<PluginItem[]>('/plugins/refresh')
  return data
}

export async function updatePlugin(pluginKey: string, payload: Partial<{ enabled: boolean; priority: number; config: Record<string, any> }>) {
  const { data } = await http.patch<PluginItem>(`/plugins/${pluginKey}`, payload)
  return data
}

export async function fetchSyncPlugins() {
  const { data } = await http.get<PluginItem[]>('/sync-plugins')
  return data
}

export async function refreshSyncPlugins() {
  const { data } = await http.post<PluginItem[]>('/sync-plugins/refresh')
  return data
}

export async function updateSyncPlugin(pluginKey: string, payload: Partial<{ enabled: boolean; priority: number; config: Record<string, any> }>) {
  const { data } = await http.patch<PluginItem>(`/sync-plugins/${pluginKey}`, payload)
  return data
}
