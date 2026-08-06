import { http } from '@/api/http'
import type { OpenListConfig } from '@/types/openlist'
import type { PathBrowseResponse } from '@/types/pathBrowse'

export async function fetchOpenListConfig() {
  const { data } = await http.get<OpenListConfig>('/openlist/config')
  return data
}

export async function patchOpenListConfig(payload: { url?: string | null; token?: string | null }) {
  const { data } = await http.patch<OpenListConfig>('/openlist/config', payload)
  return data
}

export async function browseOpenList(payload: { path: string; refresh?: boolean; max_items?: number }) {
  const { data } = await http.post<PathBrowseResponse>('/openlist/browse', payload)
  return data
}
