<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ArrowRight, Bell, Calendar, Film, HomeFilled, Menu, Setting, User } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'

import { resetDynamicRoutes } from '@/router'
import { useAuthStore } from '@/stores/auth'
import { getHealth } from '@/api/health'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const iconMap = {
  ArrowRight,
  Bell,
  Calendar,
  Film,
  HomeFilled,
  Menu,
  Setting,
  User,
}

const breadcrumbs = computed(() =>
  route.matched.filter((item) => item.meta?.title && item.meta?.breadcrumb !== false),
)

const currentTitle = computed(() => String(breadcrumbs.value.at(-1)?.meta?.title || '平台首页'))
const mobileNavVisible = ref(false)
const theme = ref<'light' | 'dark'>(getInitialTheme())
const isDark = computed({
  get: () => theme.value === 'dark',
  set: (val: boolean) => {
    theme.value = val ? 'dark' : 'light'
  },
})

const buildTag = ref<string | null>(null)
const buildSha = ref<string | null>(null)
const latestTag = ref<string | null>(null)
const updateUrl = computed(() => 'https://github.com/ozoo0/cloud-auto-save-x/releases')
const showUpdateBadge = computed(() => {
  const current = (buildTag.value || '').trim() || 'dev'
  const latest = (latestTag.value || '').trim()
  return Boolean(latest && latest !== current)
})
const versionText = computed(() => {
  const tag = (buildTag.value || '').trim() || 'dev'
  const sha = (buildSha.value || '').trim()
  if (sha) return `${tag} (${sha.slice(0, 7)})`
  return tag
})

function getInitialTheme(): 'light' | 'dark' {
  if (typeof window === 'undefined') return 'light'
  const stored = window.localStorage.getItem('theme')
  return stored === 'dark' ? 'dark' : 'light'
}

function applyTheme(value: 'light' | 'dark') {
  if (typeof document === 'undefined') return
  document.documentElement.dataset.theme = value
}

function routeIndex(path: string) {
  return path ? `/${path}`.replace(/\/+/g, '/') : '/'
}

function menuRouteIndex(route: any, parent?: any) {
  const current = String(route?.path || '').trim()
  if (!parent) return routeIndex(current)
  if (!current) return routeIndex(String(parent?.path || '').trim())
  if (current.startsWith('/')) return routeIndex(current)
  const base = String(parent?.path || '').trim()
  return routeIndex(`${base}/${current}`)
}

function collectRouteNames(routes: any[]) {
  const names: string[] = []
  const walk = (item: any) => {
    if (typeof item?.name === 'string') names.push(item.name)
    const children = Array.isArray(item?.children) ? item.children : []
    for (const child of children) walk(child)
  }
  for (const r of routes || []) walk(r)
  return names
}

function handleMenuSelect() {
  mobileNavVisible.value = false
}

async function handleLogout() {
  const routeNames = collectRouteNames(auth.dynamicRoutes)

  await auth.logout()
  resetDynamicRoutes(routeNames)
  router.replace('/login')
}

async function checkNewVersion() {
  try {
    const res = await fetch('https://api.github.com/repos/ozoo0/cloud-auto-save-x/tags', {
      method: 'GET',
      headers: { Accept: 'application/vnd.github+json' },
    })
    if (!res.ok) return
    const data = (await res.json()) as Array<{ name?: string }>
    const tag = String(data?.[0]?.name || '').trim()
    latestTag.value = tag || null
  } catch {
    latestTag.value = null
  }
}

function openUpdatePage() {
  if (!showUpdateBadge.value) return
  if (typeof window === 'undefined') return
  window.open(updateUrl.value, '_blank')
}

onMounted(async () => {
  try {
    const health = await getHealth()
    buildTag.value = health.build_tag || 'dev'
    buildSha.value = health.build_sha || null
  } catch {
    buildTag.value = 'dev'
    buildSha.value = null
  }
  await checkNewVersion()
})

watch(
  theme,
  (value) => {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem('theme', value)
    }
    applyTheme(value)
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('theme-change', { detail: value }))
    }
  },
  { immediate: true },
)
</script>

<template>
  <div class="app-shell">
    <aside class="app-aside">
      <div class="glass-panel app-nav-card">
        <div class="app-logo">
          <div class="app-logo__mark"> CASX </div>
          <div>
            <div class="app-logo__title">追剧一体化平台</div>
            <div class="app-logo__subtitle">全自动化追剧平台</div>
          </div>
        </div>

        <el-menu router :default-active="route.path" class="app-menu">
          <template v-for="item in auth.menuRoutes" :key="String(item.name)">
            <el-sub-menu v-if="item.children?.some((child) => !child.meta?.hidden)" :index="routeIndex(item.path)">
              <template #title>
                <el-icon>
                  <component :is="iconMap[item.meta?.icon as keyof typeof iconMap] || User" />
                </el-icon>
                <span>{{ item.meta?.title }}</span>
              </template>
              <el-menu-item
                v-for="child in item.children?.filter((c) => !c.meta?.hidden) || []"
                :key="String(child.name)"
                :index="menuRouteIndex(child, item)"
              >
                <el-icon>
                  <component :is="iconMap[child.meta?.icon as keyof typeof iconMap] || iconMap[item.meta?.icon as keyof typeof iconMap] || User" />
                </el-icon>
                <span>{{ child.meta?.title }}</span>
              </el-menu-item>
            </el-sub-menu>
            <el-menu-item v-else :index="routeIndex(item.path)">
              <el-icon>
                <component :is="iconMap[item.meta?.icon as keyof typeof iconMap] || User" />
              </el-icon>
              <span>{{ item.meta?.title }}</span>
            </el-menu-item>
          </template>
        </el-menu>

        <div class="app-aside-actions">
          <div class="app-aside-actions__row">
            <span class="app-aside-actions__label">主题</span>
            <el-switch v-model="isDark" inline-prompt active-text="暗" inactive-text="亮" />
          </div>
          <div class="app-aside-actions__row">
            <span class="app-aside-actions__label">版本</span>
            <el-badge
              :value="latestTag || ''"
              :hidden="!showUpdateBadge"
              type="danger"
              :offset="[-6, -2]"
              class="app-version-badge"
            >
              <span
                class="app-version"
                :class="{ 'app-version--clickable': showUpdateBadge }"
                :title="showUpdateBadge ? `发现新版本：${latestTag}` : `${buildTag || ''} ${buildSha || ''}`.trim()"
                @click="openUpdatePage"
              >
                {{ versionText }}
              </span>
            </el-badge>
          </div>
          <div class="app-aside-actions__row">
            <span class="app-aside-actions__label">账号</span>
            <el-button type="primary" @click="handleLogout">退出登录</el-button>
          </div>
        </div>
      </div>
    </aside>

    <el-drawer
      :model-value="mobileNavVisible"
      direction="ltr"
      size="320px"
      class="app-mobile-drawer"
      @close="mobileNavVisible = false"
    >
      <template #header>
        <div class="app-logo app-logo--drawer">
          <div class="app-logo__mark">XM</div>
          <div>
            <div class="app-logo__title">追剧一体化平台</div>
            <div class="app-logo__subtitle">导航 · {{ versionText }}</div>
          </div>
        </div>
      </template>
      <el-menu
        router
        :default-active="route.path"
        class="app-menu app-menu--drawer"
        @select="handleMenuSelect"
      >
        <template v-for="item in auth.menuRoutes" :key="String(item.name)">
          <el-sub-menu v-if="item.children?.some((child) => !child.meta?.hidden)" :index="routeIndex(item.path)">
            <template #title>
              <el-icon>
                <component :is="iconMap[item.meta?.icon as keyof typeof iconMap] || User" />
              </el-icon>
              <span>{{ item.meta?.title }}</span>
            </template>
            <el-menu-item
              v-for="child in item.children?.filter((c) => !c.meta?.hidden) || []"
              :key="String(child.name)"
              :index="menuRouteIndex(child, item)"
            >
              <el-icon>
                <component :is="iconMap[child.meta?.icon as keyof typeof iconMap] || iconMap[item.meta?.icon as keyof typeof iconMap] || User" />
              </el-icon>
              <span>{{ child.meta?.title }}</span>
            </el-menu-item>
          </el-sub-menu>
          <el-menu-item v-else :index="routeIndex(item.path)">
            <el-icon>
              <component :is="iconMap[item.meta?.icon as keyof typeof iconMap] || User" />
            </el-icon>
            <span>{{ item.meta?.title }}</span>
          </el-menu-item>
        </template>
      </el-menu>
    </el-drawer>

    <main class="app-content">
      <header class="glass-panel app-header">
        <div class="app-header__left">
          <el-button text class="app-header__menu" @click="mobileNavVisible = true">
            <el-icon><Menu /></el-icon>
          </el-button>
          <div class="app-header__meta">
            <div class="app-header__eyebrow">控制台</div>
            <div class="app-header__title">{{ currentTitle }}</div>
            <el-breadcrumb :separator-icon="ArrowRight">
              <el-breadcrumb-item v-for="item in breadcrumbs" :key="item.path">
                {{ item.meta?.title }}
              </el-breadcrumb-item>
            </el-breadcrumb>
          </div>
        </div>
        <div class="app-header__right">
          <el-switch v-model="isDark" inline-prompt active-text="暗" inactive-text="亮" class="app-header__theme" />
          <div class="app-user-chip">
            <div class="app-user-chip__name">{{ auth.user?.username }}</div>
            <div class="app-user-chip__meta">{{ auth.roles.join(' / ') || '已登录' }}</div>
          </div>
          <el-button type="primary" class="desktop-only" @click="handleLogout">退出登录</el-button>
          <el-dropdown class="mobile-only" @command="handleLogout">
            <el-button type="primary" class="app-header__user">
              <el-icon><User /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <div class="app-main">
        <RouterView />
      </div>
    </main>
  </div>
</template>
