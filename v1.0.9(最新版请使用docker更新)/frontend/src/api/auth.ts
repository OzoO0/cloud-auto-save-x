import { http } from '@/api/http'
import type { LoginResponse, MeResponse } from '@/types/auth'

export async function loginApi(username: string, password: string) {
  const body = new URLSearchParams()
  body.set('username', username)
  body.set('password', password)

  const { data } = await http.post<LoginResponse>('/auth/login', body, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  })
  return data
}

export async function refreshApi() {
  const { data } = await http.post<{ access_token: string; expires_in: number }>('/auth/refresh')
  return data
}

export async function logoutApi() {
  const { data } = await http.post('/auth/logout')
  return data
}

export async function meApi() {
  const { data } = await http.get<MeResponse>('/auth/me')
  return data
}
