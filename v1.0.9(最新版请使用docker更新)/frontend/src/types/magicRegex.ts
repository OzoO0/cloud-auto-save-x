export type MagicRegexRuleSetting = {
  key: string
  label?: string | null
  enabled: boolean
  built_in: boolean
  overridden: boolean
  pattern: string
  replace: string
  default_pattern?: string | null
  default_replace?: string | null
}

export type MagicRegexRuleListResponse = {
  rules: MagicRegexRuleSetting[]
}
