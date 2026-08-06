import { http } from '@/api/http'
import type { MagicRegexRuleListResponse } from '@/types/magicRegex'

export async function fetchMagicRegexRules() {
  const { data } = await http.get<MagicRegexRuleListResponse>('/magic-regex/rules')
  return data
}

export async function upsertMagicRegexRule(key: string, payload: Partial<{ label: string | null; pattern: string | null; replace: string | null; enabled: boolean }>) {
  const { data } = await http.patch<MagicRegexRuleListResponse>(`/magic-regex/rules/${encodeURIComponent(key)}`, payload)
  return data
}

export async function deleteMagicRegexRule(key: string) {
  const { data } = await http.delete<MagicRegexRuleListResponse>(`/magic-regex/rules/${encodeURIComponent(key)}`)
  return data
}
