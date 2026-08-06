import { http } from './http'

export type HealthOut = {
  status: 'ok' | 'degraded'
  db_connected: boolean
  time: string
  build_sha?: string | null
  build_tag?: string | null
}

export async function getHealth() {
  const res = await http.get<HealthOut>('/health', { headers: { 'X-Silent-Toast': '1' } })
  return res.data
}

