import type { RouteRecordRaw } from 'vue-router'

import { AUDIT_READ, DRIVE_ACCOUNT_READ, NOTIFY_READ, PLUGIN_READ, SYNC_READ, TASK_READ, TASK_WRITE, USER_READ, USER_WRITE } from '@/constants/permissions'

declare module 'vue-router' {
  interface RouteMeta {
    title?: string
    icon?: string
    hidden?: boolean
    permissions?: string[]
    breadcrumb?: boolean
    public?: boolean
  }
}

export const constantRoutes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginView.vue'),
    meta: { title: '登录', public: true, hidden: true },
  },
  {
    path: '/setup',
    name: 'SetupWizard',
    component: () => import('@/views/SetupWizardView.vue'),
    meta: { title: '初始化', public: true, hidden: true },
  },
  {
    path: '/403',
    name: 'Forbidden',
    component: () => import('@/views/ForbiddenView.vue'),
    meta: { title: '无权限', public: true, hidden: true },
  },
]

export const appRoutes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'RootLayout',
    component: () => import('@/layouts/AppLayout.vue'),
    meta: { title: '平台首页' },
    children: [
      {
        path: '',
        name: 'Dashboard',
        component: () => import('@/views/DashboardView.vue'),
        meta: { title: '工作台', icon: 'HomeFilled', breadcrumb: false },
      },
      {
        path: 'tasks/calendar',
        name: 'DramaCalendar',
        component: () => import('@/views/tasks/DramaCalendarView.vue'),
        meta: { title: '追剧日历', icon: 'Calendar', permissions: [TASK_READ] },
      },
      {
        path: 'discover',
        name: 'MediaDiscover',
        component: () => import('@/views/media/MediaDiscoverView.vue'),
        meta: { title: '影视发现', icon: 'Film', permissions: [TASK_READ] },
      },
      {
        path: 'tasks/drama',
        name: 'DramaTasks',
        component: () => import('@/views/tasks/DramaTaskView.vue'),
        meta: { title: '追剧任务', icon: 'Setting', permissions: [TASK_READ] },
      },
      {
        path: 'tasks/sync',
        name: 'SyncTasks',
        component: () => import('@/views/tasks/SyncTaskView.vue'),
        meta: { title: '同步任务', icon: 'Refresh', permissions: [SYNC_READ] },
      },
      {
        path: 'extensions/drives',
        name: 'DriveAccounts',
        component: () => import('@/views/extensions/DriveAccountView.vue'),
        meta: { title: '账号管理', icon: 'Setting', permissions: [DRIVE_ACCOUNT_READ] },
      },
      {
        path: 'extensions/drives/auth/:accountId',
        name: 'DriveAccountAuth',
        component: () => import('@/views/extensions/DriveAccountAuthView.vue'),
        meta: { title: '账号二次认证', hidden: true, permissions: [DRIVE_ACCOUNT_READ] },
      },
      {
        path: 'extensions/plugins',
        name: 'Plugins',
        component: () => import('@/views/extensions/PluginManagerView.vue'),
        meta: { title: '插件管理', icon: 'Setting', permissions: [PLUGIN_READ] },
      },
      {
        path: 'extensions/notifications',
        name: 'Notifications',
        component: () => import('@/views/extensions/NotificationConfigView.vue'),
        meta: { title: '通知配置', icon: 'Bell', permissions: [NOTIFY_READ] },
      },
      {
        path: 'cache',
        name: 'CacheManagement',
        component: () => import('@/views/cache/CacheLayoutView.vue'),
        redirect: '/cache/tmdb',
        meta: { title: '缓存管理', icon: 'Setting', permissions: [TASK_WRITE] },
        children: [
          {
            path: 'tmdb',
            name: 'CacheTMDB',
            component: () => import('@/views/extensions/TMDBCacheManageView.vue'),
            meta: { title: 'TMDB 缓存', icon: 'Setting', permissions: [TASK_WRITE] },
          },
          {
            path: 'share-links',
            name: 'CacheShareLinks',
            component: () => import('@/views/cache/ShareLinkCacheManageView.vue'),
            meta: { title: '分享链接缓存', icon: 'Setting', permissions: [TASK_WRITE] },
          },
          {
            path: 'proxy-image',
            name: 'CacheProxyImage',
            component: () => import('@/views/cache/ProxyImageCacheManageView.vue'),
            meta: { title: '代理图片缓存', icon: 'Setting', permissions: [TASK_WRITE] },
          },
        ],
      },
      {
        path: 'tmdb-cache',
        name: 'TMDBCacheLegacy',
        redirect: '/cache/tmdb',
        meta: { title: 'TMDB 缓存', icon: 'Setting', hidden: true, permissions: [TASK_WRITE] },
      },
      {
        path: 'users',
        name: 'Users',
        component: () => import('@/views/users/UserListView.vue'),
        meta: { title: '用户管理', icon: 'User', permissions: [USER_READ] },
      },
      {
        path: 'users/create',
        name: 'UserCreate',
        component: () => import('@/views/users/UserListView.vue'),
        meta: { title: '创建用户', hidden: true, permissions: [USER_WRITE] },
      },
      {
        path: 'settings',
        name: 'SystemSettings',
        component: () => import('@/views/extensions/MagicRegexView.vue'),
        meta: { title: '系统设置', icon: 'Setting', permissions: [TASK_WRITE] },
      },
      {
        path: 'extensions/audit-logs',
        name: 'AuditLogs',
        component: () => import('@/views/extensions/AuditLogView.vue'),
        meta: { title: '审计日志', icon: 'Setting', permissions: [AUDIT_READ] },
      },
    ],
  },
]
