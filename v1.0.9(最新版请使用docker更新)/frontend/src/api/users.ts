import { http } from '@/api/http'
import type { RoleDetail, UserListResponse } from '@/types/user'

export async function fetchUsers(params: { page: number; page_size: number; q?: string }) {
  const { data } = await http.get<UserListResponse>('/users', { params })
  return data
}

export async function createUser(payload: { username: string; email: string; password: string }) {
  const { data } = await http.post('/users', payload)
  return data
}

export async function setUserStatus(userId: number, is_active: boolean) {
  const { data } = await http.patch(`/users/${userId}/status`, { is_active })
  return data
}

export async function setUserRoles(userId: number, role_ids: number[]) {
  const { data } = await http.post(`/users/${userId}/roles`, { role_ids })
  return data
}

export async function batchSetUserStatus(user_ids: number[], is_active: boolean) {
  const { data } = await http.post('/users/batch/status', { user_ids, is_active })
  return data
}

export async function batchSetUserRoles(user_ids: number[], role_ids: number[]) {
  const { data } = await http.post('/users/batch/roles', { user_ids, role_ids })
  return data
}

export async function fetchRoles() {
  const { data } = await http.get<RoleDetail[]>('/roles')
  return data
}

export async function fetchPermissions() {
  const { data } = await http.get('/permissions')
  return data
}
