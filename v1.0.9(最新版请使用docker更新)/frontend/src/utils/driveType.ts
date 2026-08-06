export type DriveType = 'quark' | '115' | 'baidu' | 'xunlei' | 'aliyun' | 'uc' | '123pan' | 'cloud189' | 'cloud139' | 'guangya'

export function detectDriveTypeByUrl(url: string): DriveType | null {
  const value = String(url || '')
  if (!value) return null
  if (/pan\.quark\.cn/i.test(value)) return 'quark'
  if (/(?:115|anxia|115cdn)\.com/i.test(value)) return '115'
  if (/pan\.baidu\.com/i.test(value)) return 'baidu'
  if (/pan\.xunlei\.com/i.test(value)) return 'xunlei'
  if (/(?:alipan|aliyundrive)\.com/i.test(value)) return 'aliyun'
  if (/drive\.uc\.cn/i.test(value)) return 'uc'
  if (/(?:123pan|123865|123684|123952|123912)\.com/i.test(value)) return '123pan'
  if (/(?:cloud|m\.cloud)\.189\.cn/i.test(value)) return 'cloud189'
  if (/(?:yun|caiyun)\.139\.com/i.test(value)) return 'cloud139'
  if (/(?:www\.|app\.)?guangyapan\.com/i.test(value)) return 'guangya'
  return null
}
