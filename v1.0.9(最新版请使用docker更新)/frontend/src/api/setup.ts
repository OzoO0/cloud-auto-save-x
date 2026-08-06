import { http } from '@/api/http'
import type { LoginResponse } from '@/types/auth'

export type SetupStatusResponse = {
  initialized: boolean
}

export async function getSetupStatus() {
  const { data } = await http.get<SetupStatusResponse>('/setup/status')
  return data
}

export async function initAdmin(payload: { username: string; email: string; password: string }) {
  const { data } = await http.post<LoginResponse>('/setup/admin', payload)
  return data
}

