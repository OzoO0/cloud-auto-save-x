import axios, { type AxiosError, type AxiosInstance, type AxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'

import { useAuthStore } from '@/stores/auth'
import { router } from '@/router'

type ApiErrorBody = {
  code?: string
  message?: string
  detail?: string
}

const DEFAULT_TIMEOUT_MS = 50000
const AUTH_EXCLUDED_PATHS = ['/auth/login', '/auth/refresh']

function shouldRetry(config: AxiosRequestConfig) {
  const method = (config.method || 'get').toLowerCase()
  return method === 'get' || (config.headers && (config.headers as any)['X-Retryable'] === '1')
}

function getRequestPath(config?: AxiosRequestConfig) {
  return config?.url || ''
}

function shouldAttemptRefresh(config?: AxiosRequestConfig, hasAccessToken?: boolean) {
  const path = getRequestPath(config)
  if (!hasAccessToken) return false
  return !AUTH_EXCLUDED_PATHS.some((item) => path.includes(item))
}

async function sleep(ms: number) {
  await new Promise((r) => setTimeout(r, ms))
}

async function withRetry<T>(fn: () => Promise<T>, retries: number) {
  let lastErr: unknown
  for (let i = 0; i <= retries; i++) {
    try {
      return await fn()
    } catch (e) {
      lastErr = e
      if (i === retries) break
      await sleep(200 * Math.pow(2, i))
    }
  }
  throw lastErr
}

let refreshPromise: Promise<string> | null = null

export function createHttpClient(): AxiosInstance {
  const instance = axios.create({
    baseURL: '/api',
    timeout: DEFAULT_TIMEOUT_MS,
    withCredentials: true,
  })

  instance.interceptors.request.use((config) => {
    const auth = useAuthStore()
    if (auth.accessToken) {
      config.headers = config.headers || {}
      ;(config.headers as any).Authorization = `Bearer ${auth.accessToken}`
    }
    return config
  })

  instance.interceptors.response.use(
    (res) => res,
    async (error: AxiosError<ApiErrorBody>) => {
      const auth = useAuthStore()
      const status = error.response?.status
      const data = error.response?.data

      const originalConfig = error.config as (AxiosRequestConfig & { _retry?: boolean }) | undefined
      const silentToast = Boolean(originalConfig?.headers && (originalConfig.headers as any)['X-Silent-Toast'])

      if (
        status === 401 &&
        originalConfig &&
        !originalConfig._retry &&
        shouldAttemptRefresh(originalConfig, Boolean(auth.accessToken))
      ) {
        originalConfig._retry = true

        try {
          refreshPromise =
            refreshPromise ||
            axios
              .post(
                '/api/auth/refresh',
                {},
                {
                  withCredentials: true,
                  timeout: DEFAULT_TIMEOUT_MS,
                },
              )
              .then((r) => r.data.access_token as string)
              .finally(() => {
                refreshPromise = null
              })

          const newToken = await refreshPromise
          auth.setAccessToken(newToken)
          originalConfig.headers = originalConfig.headers || {}
          ;(originalConfig.headers as any).Authorization = `Bearer ${newToken}`
          return instance.request(originalConfig)
        } catch (e) {
          auth.clear()
          if (router.currentRoute.value.path !== '/login') {
            router.replace({ path: '/login', query: { redirect: router.currentRoute.value.fullPath } })
          }
          return Promise.reject(e)
        }
      }

      if (status === 403) {
        if (!silentToast) ElMessage.error(data?.message || '权限不足')
        if (router.currentRoute.value.path !== '/403') {
          router.replace('/403')
        }
        return Promise.reject(error)
      }

      if (status && status >= 500) {
        if (!silentToast) ElMessage.error(data?.message || '服务异常')
        return Promise.reject(error)
      }

      if (!error.response) {
        if (originalConfig && shouldRetry(originalConfig)) {
          return withRetry(() => instance.request(originalConfig), 2)
        }
        if (!silentToast) ElMessage.error('网络异常')
        return Promise.reject(error)
      }

      if (data?.message) {
        if (!silentToast) ElMessage.error(data.message)
      }

      return Promise.reject(error)
    },
  )

  return instance
}

export const http = createHttpClient()
