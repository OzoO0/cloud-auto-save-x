import { http } from '@/api/http'
import type { TMDBConfig } from '@/types/tmdb'

export async function fetchTMDBConfig() {
  const response = await http.get<TMDBConfig>('/tmdb/config')
  return response.data
}

export async function patchTMDBConfig(payload: {
  api_key?: string | null
  language?: string | null
  poster_language?: string | null
  disable_guessit_tmdb_fallback_rename?: boolean | null
}) {
  const response = await http.patch<TMDBConfig>('/tmdb/config', payload)
  return response.data
}
