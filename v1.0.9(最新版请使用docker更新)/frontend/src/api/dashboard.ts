import { http } from '@/api/http'
import type { CapacityOverview, DramaOverview } from '@/types/dashboard'

export async function fetchCapacityOverview() {
  const { data } = await http.get<CapacityOverview>('/dashboard/capacity-overview')
  return data
}

export async function fetchDramaOverview(days = 30) {
  const { data } = await http.get<DramaOverview>('/dashboard/drama-overview', { params: { days } })
  return data
}
