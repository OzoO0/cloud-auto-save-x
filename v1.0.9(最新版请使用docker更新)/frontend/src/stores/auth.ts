import { defineStore } from 'pinia'
import type { RouteRecordRaw } from 'vue-router'

import { loginApi, logoutApi, meApi, refreshApi } from '@/api/auth'
import { appRoutes } from '@/router/routes'
import type { LoginResponse, MeResponse } from '@/types/auth'

function filterRoutesByPermissions(routes: RouteRecordRaw[], permissions: string[]): RouteRecordRaw[] {
  return routes
    .filter((route) => {
      const routePerms = route.meta?.permissions
      if (!routePerms?.length) return true
      return routePerms.every((p) => permissions.includes(p))
    })
    .map((route) => {
      const nextRoute: RouteRecordRaw = { ...route }
      if (route.children) {
        nextRoute.children = filterRoutesByPermissions(route.children, permissions)
      }
      return nextRoute
    })
}

let bootstrapPromise: Promise<void> | null = null

export const useAuthStore = defineStore('auth', {
  state: () => ({
    accessToken: '' as string,
    user: null as MeResponse | null,
    initialized: false,
    loading: false,
    dynamicRoutes: [] as RouteRecordRaw[],
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.accessToken && state.user),
    permissions: (state) => state.user?.permissions || [],
    roles: (state) => state.user?.roles || [],
    menuRoutes(state) {
      const root = state.dynamicRoutes.find((item) => item.path === '/')
      return root?.children?.filter((item) => !item.meta?.hidden) || []
    },
  },
  actions: {
    setAccessToken(token: string) {
      this.accessToken = token
    },
    applyUser(user: MeResponse) {
      this.user = user
      this.dynamicRoutes = filterRoutesByPermissions(appRoutes, user.permissions)
      this.initialized = true
    },
    clear() {
      this.accessToken = ''
      this.user = null
      this.dynamicRoutes = []
      this.initialized = true
    },
    async afterLogin(payload: LoginResponse) {
      this.accessToken = payload.access_token
      this.applyUser(payload.user)
    },
    async login(username: string, password: string) {
      const data = await loginApi(username, password)
      await this.afterLogin(data)
    },
    async bootstrap() {
      if (this.initialized) return
      if (bootstrapPromise) return bootstrapPromise

      this.loading = true
      bootstrapPromise = (async () => {
        try {
          const refresh = await refreshApi()
          this.accessToken = refresh.access_token
          const me = await meApi()
          this.applyUser(me)
        } catch {
          this.clear()
        } finally {
          this.loading = false
          bootstrapPromise = null
        }
      })()

      return bootstrapPromise
    },
    async reloadMe() {
      const me = await meApi()
      this.applyUser(me)
    },
    async logout() {
      try {
        await logoutApi()
      } finally {
        this.clear()
      }
    },
  },
})
