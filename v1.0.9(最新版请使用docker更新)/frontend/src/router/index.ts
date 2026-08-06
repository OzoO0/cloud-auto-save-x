import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import { constantRoutes } from '@/router/routes'
import { useAuthStore } from '@/stores/auth'
import { useSetupStore } from '@/stores/setup'

export const router = createRouter({
  history: createWebHistory(),
  routes: constantRoutes,
})

let dynamicReady = false

export function resetDynamicRoutes(names: string[]) {
  for (const name of names) {
    if (router.hasRoute(name)) {
      router.removeRoute(name)
    }
  }
  dynamicReady = false
}

export function appendDynamicRoutes(routes: RouteRecordRaw[]) {
  if (dynamicReady) return
  for (const route of routes) {
    router.addRoute(route)
  }
  dynamicReady = true
}

router.beforeEach(async (to) => {
  const setup = useSetupStore()
  try {
    await setup.refreshStatus()
  } catch {
    if (to.path !== '/setup') {
      return { path: '/setup', query: { pending: '1', redirect: to.fullPath } }
    }
    return true
  }

  if (!setup.initialized) {
    if (to.path !== '/setup') {
      return { path: '/setup', query: { redirect: to.fullPath } }
    }
    return true
  }

  const auth = useAuthStore()

  if (to.meta.public) {
    if (to.path === '/login' && auth.isAuthenticated) {
      return { path: '/' }
    }
    if (to.path === '/setup') {
      if (auth.isAuthenticated) return { path: '/' }
      return { path: '/login' }
    }
    return true
  }

  await auth.bootstrap()

  if (!auth.isAuthenticated) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  if (!dynamicReady) {
    appendDynamicRoutes(auth.dynamicRoutes)
    return to.fullPath
  }

  if (to.meta.permissions?.length && !to.meta.permissions.every((perm) => auth.permissions.includes(perm))) {
    return '/403'
  }

  return true
})
