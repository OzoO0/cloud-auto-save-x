import { onBeforeUnmount, onMounted, ref } from 'vue'

export function useIsMobile(maxWidth = 767) {
  const isMobile = ref(false)
  let mql: MediaQueryList | null = null
  let handler: ((e: MediaQueryListEvent) => void) | null = null

  const sync = () => {
    isMobile.value = Boolean(mql?.matches)
  }

  onMounted(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return
    mql = window.matchMedia(`(max-width: ${maxWidth}px)`)
    handler = () => sync()
    sync()
    if (mql.addEventListener) mql.addEventListener('change', handler)
    else (mql as any).addListener(handler)
  })

  onBeforeUnmount(() => {
    if (!mql || !handler) return
    if (mql.removeEventListener) mql.removeEventListener('change', handler)
    else (mql as any).removeListener(handler)
    mql = null
    handler = null
  })

  return isMobile
}

