export const DEFAULT_TIMEZONE = 'Asia/Shanghai'

function normalizeSpaces(value: string) {
  return value.trim().replace(/\s+/g, ' ')
}

function isInt(value: string) {
  return /^\d+$/.test(value)
}

function parseIntSafe(value: string) {
  if (!isInt(value)) return null
  const n = Number(value)
  if (!Number.isFinite(n)) return null
  return n
}

function validateNumberRange(value: number, min: number, max: number) {
  return value >= min && value <= max
}

function validateStep(value: string) {
  const n = parseIntSafe(value)
  if (n === null) return false
  return n >= 1
}

function validateRangeToken(token: string, min: number, max: number) {
  const [aStr, bStr] = token.split('-', 2)
  const a = parseIntSafe(aStr)
  const b = parseIntSafe(bStr)
  if (a === null || b === null) return null
  if (!validateNumberRange(a, min, max) || !validateNumberRange(b, min, max)) return false
  return a <= b
}

function normalizeDayOfWeekToken(token: string) {
  const map: Record<string, number> = {
    sun: 0,
    mon: 1,
    tue: 2,
    wed: 3,
    thu: 4,
    fri: 5,
    sat: 6,
  }
  const lower = token.toLowerCase()
  if (map[lower] !== undefined) return String(map[lower])
  return token
}

function validateFieldToken(tokenRaw: string, min: number, max: number, opts?: { dayOfWeek?: boolean }) {
  let token = tokenRaw.trim()
  if (!token) return false
  if (opts?.dayOfWeek) token = normalizeDayOfWeekToken(token)
  if (token === '*' || token === '?') return true

  if (token.includes('/')) {
    const [left, step] = token.split('/', 2)
    if (!validateStep(step)) return false
    if (left === '*') return true
    if (left.includes('-')) {
      const ok = validateRangeToken(left, min, max)
      if (ok === null) return true
      return ok
    }
    return true
  }

  if (token.includes('-')) {
    const ok = validateRangeToken(token, min, max)
    if (ok === null) return true
    return ok
  }

  const n = parseIntSafe(token)
  if (n === null) return true
  return validateNumberRange(n, min, max)
}

export function normalizeCrontab(value: string) {
  return normalizeSpaces(String(value || ''))
}

export function validateCrontab5(value: string) {
  const normalized = normalizeCrontab(value)
  if (!normalized) return { ok: false, message: 'crontab 不能为空' }
  const parts = normalized.split(' ')
  if (parts.length !== 5) return { ok: false, message: 'crontab 必须是 5 段：minute hour day month day_of_week' }

  const fields: Array<{ min: number; max: number; label: string; dayOfWeek?: boolean }> = [
    { min: 0, max: 59, label: 'minute' },
    { min: 0, max: 23, label: 'hour' },
    { min: 1, max: 31, label: 'day' },
    { min: 1, max: 12, label: 'month' },
    { min: 0, max: 6, label: 'day_of_week', dayOfWeek: true },
  ]

  for (let i = 0; i < fields.length; i += 1) {
    const field = fields[i]
    const raw = parts[i]
    const tokens = raw.split(',')
    for (const token of tokens) {
      if (!validateFieldToken(token, field.min, field.max, { dayOfWeek: field.dayOfWeek })) {
        return { ok: false, message: `crontab 第 ${i + 1} 段（${field.label}）范围应为 ${field.min}-${field.max}` }
      }
    }
  }

  return { ok: true, message: '', normalized }
}

export function normalizeTimezone(value: string) {
  const text = String(value || '').trim()
  return text || DEFAULT_TIMEZONE
}

export function validateTimezone(value: string) {
  const tz = normalizeTimezone(value)
  try {
    new Intl.DateTimeFormat('zh-CN', { timeZone: tz }).format(new Date())
  } catch (e: any) {
    if (e?.name === 'RangeError') return { ok: false, message: `timezone 无效：${tz}`, normalized: tz }
  }
  return { ok: true, message: '', normalized: tz }
}
