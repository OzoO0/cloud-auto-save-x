<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  deleteTMDBCacheItem,
  fetchTMDBCacheItem,
  fetchTMDBCacheList,
  fetchTMDBCacheScheduler,
  fetchTMDBCacheStatus,
  patchTMDBCacheScheduler,
  purgeTMDBCache,
  refreshLinkedTasks,
  refreshTMDBCache,
  setTMDBCacheTTL,
} from '@/api/tmdbCache'
import { TASK_WRITE } from '@/constants/permissions'
import { useAuthStore } from '@/stores/auth'
import { useIsMobile } from '@/composables/useIsMobile'
import type { TMDBCacheItem, TMDBCacheListItem, TMDBCacheSchedulerSetting, TMDBCacheStatus } from '@/types/tmdbCache'
import { validateCrontab5, validateTimezone } from '@/utils/cron'

const auth = useAuthStore()
const canWrite = computed(() => auth.permissions.includes(TASK_WRITE))
const isMobile = useIsMobile()
const activeTab = ref<'list' | 'tools' | 'scheduler'>('list')

type MediaType = '' | 'movie' | 'tv'
type TTLUnit = 'minute' | 'hour' | 'day'

const PAYLOAD_PREVIEW_LIMIT = 50_000
const PAYLOAD_PRETTY_LIMIT = 200_000

function fmtTime(value?: string | null) {
  if (!value) return '-'
  const s = String(value)
  const hasTz = /([zZ]|[+-]\d{2}:\d{2})$/.test(s)
  const d = new Date(hasTz ? s : `${s}Z`)
  if (Number.isNaN(d.getTime())) return String(value)
  return d.toLocaleString()
}

function toSeconds(value: number, unit: TTLUnit) {
  const v = Math.max(1, Math.floor(Number(value || 0)))
  if (unit === 'minute') return v * 60
  if (unit === 'hour') return v * 60 * 60
  return v * 24 * 60 * 60
}

const loadingAll = ref(false)

const scheduler = reactive({
  loading: false,
  saving: false,
  data: {
    enabled: true,
    crontab: '0 */6 * * *',
    timezone: 'Asia/Shanghai',
    max_items_per_run: 200,
    only_refresh_linked_tasks: true,
    retention_days: 60,
  } as TMDBCacheSchedulerSetting,
})

const tools = reactive({
  refreshingLinked: false,
  purging: false,
  enabledOnly: true,
  maxItems: 200,
  force: true,
  retentionDays: 60,
})

const actionDialog = reactive({
  visible: false,
  icon: 'success' as 'success' | 'warning' | 'error' | 'info',
  title: '',
  subTitle: '',
  meta: {} as Record<string, any>,
})

function openActionDialog(payload: { icon: typeof actionDialog.icon; title: string; subTitle?: string; meta?: Record<string, any> }) {
  actionDialog.icon = payload.icon
  actionDialog.title = payload.title
  actionDialog.subTitle = payload.subTitle || ''
  actionDialog.meta = payload.meta || {}
  actionDialog.visible = true
}

const query = reactive({
  mediaType: '' as MediaType,
  keyword: '',
  status: '',
  expiredOnly: false,
})

const list = reactive({
  loading: false,
  configured: false,
  page: 1,
  pageSize: 20,
  total: 0,
  items: [] as TMDBCacheListItem[],
})

const quick = reactive({
  mediaType: 'tv' as Exclude<MediaType, ''>,
  tmdbId: null as number | null,
  loading: false,
  status: null as TMDBCacheStatus | null,
})

const drawer = reactive({
  visible: false,
  loading: false,
  row: null as TMDBCacheListItem | null,
  status: null as TMDBCacheStatus | null,
  tab: 'status' as 'status' | 'payload',
  payloadLoading: false,
  payloadItem: null as TMDBCacheItem | null,
})

const ttlDialog = reactive({
  visible: false,
  submitting: false,
  mediaType: '' as Exclude<MediaType, ''>,
  tmdbId: 0,
  value: 6,
  unit: 'hour' as TTLUnit,
})

const deleteDialog = reactive({
  visible: false,
  deleting: false,
  row: null as TMDBCacheListItem | null,
})

async function loadScheduler() {
  scheduler.loading = true
  try {
    scheduler.data = await fetchTMDBCacheScheduler()
  } finally {
    scheduler.loading = false
  }
}

async function saveScheduler() {
  if (!canWrite.value) return
  const cronCheck = validateCrontab5(String(scheduler.data.crontab || ''))
  if (!cronCheck.ok) {
    ElMessage.error(cronCheck.message)
    return
  }
  const tzCheck = validateTimezone(String(scheduler.data.timezone || ''))
  if (!tzCheck.ok) {
    ElMessage.error(tzCheck.message)
    return
  }
  scheduler.data.crontab = cronCheck.normalized || scheduler.data.crontab
  scheduler.data.timezone = tzCheck.normalized || scheduler.data.timezone
  scheduler.saving = true
  try {
    scheduler.data = await patchTMDBCacheScheduler({
      enabled: scheduler.data.enabled,
      crontab: scheduler.data.crontab,
      timezone: scheduler.data.timezone,
      max_items_per_run: scheduler.data.max_items_per_run,
      only_refresh_linked_tasks: scheduler.data.only_refresh_linked_tasks,
      retention_days: scheduler.data.retention_days,
    })
    ElMessage.success('已保存')
  } finally {
    scheduler.saving = false
  }
}

async function loadList() {
  list.loading = true
  try {
    const data = await fetchTMDBCacheList({
      page: list.page,
      page_size: list.pageSize,
      media_type: query.mediaType || undefined,
      q: query.keyword || undefined,
      status: query.status || undefined,
      expired_only: query.expiredOnly || undefined,
    })
    list.configured = Boolean(data.configured)
    list.total = Number(data.total || 0)
    list.items = data.items || []
  } finally {
    list.loading = false
  }
}

async function refreshAll() {
  loadingAll.value = true
  try {
    await Promise.all([loadScheduler(), loadList()])
  } finally {
    loadingAll.value = false
  }
}

function resetFilters() {
  query.mediaType = ''
  query.keyword = ''
  query.status = ''
  query.expiredOnly = false
  list.page = 1
  loadList()
}

function onSearch() {
  list.page = 1
  loadList()
}

async function runRefreshLinkedTasks() {
  if (!canWrite.value) return
  tools.refreshingLinked = true
  try {
    const out = await refreshLinkedTasks({
      enabled_only: tools.enabledOnly,
      max_items: tools.maxItems,
      force: tools.force,
    })
    if (!out) {
      openActionDialog({ icon: 'warning', title: '刷新失败', subTitle: '接口返回为空' })
      return
    }
    if (!out.configured) {
      openActionDialog({ icon: 'warning', title: 'TMDB 未配置', subTitle: '请先在系统设置中配置 TMDB API Key' })
      return
    }
    openActionDialog({
      icon: 'success',
      title: '刷新完成',
      subTitle: `已刷新 ${out.refreshed}/${out.targets}`,
      meta: {
        enabled_only: Boolean(tools.enabledOnly),
        max_items: Number(tools.maxItems || 0),
        force: Boolean(tools.force),
        targets: Number(out.targets || 0),
        refreshed: Number(out.refreshed || 0),
      },
    })
    await loadList()
  } catch (e: any) {
    openActionDialog({ icon: 'error', title: '刷新失败', subTitle: e?.message || '执行失败' })
  } finally {
    tools.refreshingLinked = false
  }
}

async function runPurge() {
  if (!canWrite.value) return
  const confirmed = await ElMessageBox.confirm(`确认清理冷数据？保留天数：${tools.retentionDays}`, '清理缓存', {
    type: 'warning',
    confirmButtonText: '清理',
    cancelButtonText: '取消',
  }).catch(() => false)
  if (!confirmed) return
  tools.purging = true
  try {
    const out = await purgeTMDBCache({ retention_days: tools.retentionDays })
    openActionDialog({
      icon: 'success',
      title: '清理完成',
      subTitle: `已删除 ${out.deleted}`,
      meta: { retention_days: Number(tools.retentionDays || 0), deleted: Number(out.deleted || 0) },
    })
    await loadList()
  } catch (e: any) {
    openActionDialog({ icon: 'error', title: '清理失败', subTitle: e?.message || '清理失败' })
  } finally {
    tools.purging = false
  }
}

async function openDrawer(row: TMDBCacheListItem) {
  drawer.visible = true
  drawer.row = row
  drawer.status = null
  drawer.tab = 'status'
  drawer.payloadLoading = false
  drawer.payloadItem = null
  drawer.loading = true
  try {
    drawer.status = await fetchTMDBCacheStatus({ media_type: row.media_type, tmdb_id: row.tmdb_id })
  } finally {
    drawer.loading = false
  }
}

async function loadDrawerPayload() {
  const row = drawer.row
  if (!row) return
  if (drawer.payloadLoading) return
  if (drawer.payloadItem) return
  drawer.payloadLoading = true
  try {
    drawer.payloadItem = await fetchTMDBCacheItem({ media_type: row.media_type, tmdb_id: row.tmdb_id })
  } finally {
    drawer.payloadLoading = false
  }
}

const drawerPayloadRaw = computed(() => String(drawer.payloadItem?.payload_json || ''))
const drawerPayloadSize = computed(() => drawerPayloadRaw.value.length)
const drawerPayloadTooLarge = computed(() => drawerPayloadSize.value > PAYLOAD_PRETTY_LIMIT)
const drawerPayloadPreview = computed(() => {
  const raw = drawerPayloadRaw.value
  if (!raw) return ''
  if (raw.length <= PAYLOAD_PREVIEW_LIMIT) return raw
  return `${raw.slice(0, PAYLOAD_PREVIEW_LIMIT)}\n...（已截断，仅展示前 ${PAYLOAD_PREVIEW_LIMIT} 字符；建议使用“下载”查看全文）`
})

const drawerPayloadText = computed(() => {
  const raw = drawerPayloadRaw.value.trim()
  if (!raw) return ''
  if (drawerPayloadTooLarge.value) return drawerPayloadPreview.value
  try {
    const obj = JSON.parse(raw)
    return JSON.stringify(obj, null, 2)
  } catch {
    return raw
  }
})

async function copyDrawerPayloadRaw() {
  const text = String(drawerPayloadRaw.value || '')
  if (!text) return
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
    } else {
      const textarea = document.createElement('textarea')
      textarea.value = text
      textarea.style.position = 'fixed'
      textarea.style.top = '0'
      textarea.style.left = '0'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      textarea.setSelectionRange(0, 99999)
      document.execCommand('copy')
      document.body.removeChild(textarea)
    }
    ElMessage.success('缓存数据已复制')
  } catch {
    ElMessage.error('复制失败')
  }
}

function downloadDrawerPayload() {
  const raw = String(drawerPayloadRaw.value || '')
  if (!raw) return
  const name = drawer.row ? `${drawer.row.media_type}-${drawer.row.tmdb_id}.json` : 'tmdb-cache.json'
  const blob = new Blob([raw], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function openTTLDialog(row: TMDBCacheListItem) {
  if (!canWrite.value) return
  ttlDialog.mediaType = row.media_type as Exclude<MediaType, ''>
  ttlDialog.tmdbId = row.tmdb_id
  ttlDialog.value = 6
  ttlDialog.unit = 'hour'
  ttlDialog.visible = true
}

async function submitTTL() {
  if (!canWrite.value) return
  ttlDialog.submitting = true
  try {
    const seconds = toSeconds(ttlDialog.value, ttlDialog.unit)
    const out = await setTMDBCacheTTL({
      media_type: ttlDialog.mediaType,
      tmdb_id: ttlDialog.tmdbId,
      ttl_seconds: seconds,
    })
    if (!out.updated) {
      ElMessage.warning('未找到缓存条目（可能尚未写入缓存）')
      return
    }
    ElMessage.success('已更新 TTL')
    ttlDialog.visible = false
    await loadList()
    if (drawer.visible && drawer.row && drawer.row.tmdb_id === ttlDialog.tmdbId && drawer.row.media_type === ttlDialog.mediaType) {
      drawer.status = await fetchTMDBCacheStatus({ media_type: ttlDialog.mediaType, tmdb_id: ttlDialog.tmdbId })
    }
  } finally {
    ttlDialog.submitting = false
  }
}

async function refreshRow(row: TMDBCacheListItem) {
  if (!canWrite.value) return
  await refreshTMDBCache({ media_type: row.media_type, tmdb_id: row.tmdb_id, force: true, async_refresh: false })
  ElMessage.success('已刷新')
  await loadList()
  if (drawer.visible && drawer.row && drawer.row.tmdb_id === row.tmdb_id && drawer.row.media_type === row.media_type) {
    drawer.status = await fetchTMDBCacheStatus({ media_type: row.media_type, tmdb_id: row.tmdb_id })
  }
}

function openDeleteDialog(row: TMDBCacheListItem) {
  if (!canWrite.value) return
  deleteDialog.row = row
  deleteDialog.visible = true
}

function closeDeleteDialog() {
  if (deleteDialog.deleting) return
  deleteDialog.visible = false
  deleteDialog.row = null
}

async function confirmDelete() {
  if (!canWrite.value) return
  const row = deleteDialog.row
  if (!row) return

  deleteDialog.deleting = true
  try {
    const out = await deleteTMDBCacheItem({ media_type: row.media_type, tmdb_id: row.tmdb_id })
    ElMessage.success(`已删除 ${out.deleted}`)
    if (drawer.visible && drawer.row && drawer.row.tmdb_id === row.tmdb_id && drawer.row.media_type === row.media_type) {
      drawer.visible = false
    }
    deleteDialog.deleting = false
    closeDeleteDialog()
    await loadList()
  } finally {
    deleteDialog.deleting = false
  }
}

async function quickQuery() {
  if (!quick.tmdbId) return
  quick.loading = true
  try {
    quick.status = await fetchTMDBCacheStatus({ media_type: quick.mediaType, tmdb_id: quick.tmdbId })
  } finally {
    quick.loading = false
  }
}

async function quickRefresh() {
  if (!canWrite.value) return
  if (!quick.tmdbId) return
  quick.loading = true
  try {
    const out = await refreshTMDBCache({ media_type: quick.mediaType, tmdb_id: quick.tmdbId, force: true, async_refresh: false })
    quick.status = out.status
    ElMessage.success('已刷新')
    await loadList()
  } finally {
    quick.loading = false
  }
}

watch(
  () => [query.mediaType, query.expiredOnly],
  () => {
    list.page = 1
    loadList()
  },
)

watch(
  () => drawer.tab,
  (tab) => {
    if (tab === 'payload') loadDrawerPayload()
  },
)

onMounted(refreshAll)
</script>

<template>
  <div class="page">
    <div class="page__header">
      <div class="page__title">TMDB 缓存管理</div>
    </div>

    <el-alert
      class="page__alert"
      title="这里管理的是 TMDB 详情缓存（用于任务统计/追剧信息复用）。可配置定时刷新、批量刷新任务关联条目、清理冷数据，并对单条缓存设置 TTL/强制刷新/删除。"
      type="info"
      show-icon
      :closable="false"
    />

    <el-tabs v-model="activeTab" class="tabs" :stretch="!isMobile">
      <template #extra>
        <div class="tabs__extra">
          <el-tag v-if="!list.configured" type="warning">TMDB 未配置</el-tag>
          <el-button text :loading="loadingAll" @click="refreshAll">刷新</el-button>
        </div>
      </template>

      <el-tab-pane label="缓存列表" name="list">
        <el-card class="card" shadow="never">
          <div class="filters">
            <el-select v-model="query.mediaType" placeholder="类型" clearable :style="{ width: isMobile ? '100%' : '140px' }">
              <el-option label="全部" value="" />
              <el-option label="tv" value="tv" />
              <el-option label="movie" value="movie" />
            </el-select>
            <el-input
              v-model="query.keyword"
              placeholder="标题关键词"
              clearable
              :style="{ width: isMobile ? '100%' : '240px' }"
              @keyup.enter="onSearch"
            />
            <el-input
              v-model="query.status"
              placeholder="status（精确匹配）"
              clearable
              :style="{ width: isMobile ? '100%' : '220px' }"
              @keyup.enter="onSearch"
            />
            <el-checkbox v-model="query.expiredOnly">仅过期</el-checkbox>
            <el-button :loading="list.loading" @click="onSearch">查询</el-button>
            <el-button text :disabled="list.loading" @click="resetFilters">重置</el-button>
          </div>

          <el-table
            :data="list.items"
            border
            :loading="list.loading"
            style="width: 100%"
            row-key="tmdb_id"
            @row-dblclick="openDrawer"
          >
            <el-table-column prop="media_type" label="类型" width="80" />
            <el-table-column prop="tmdb_id" label="ID" width="90" />
            <el-table-column label="标题" min-width="260">
              <template #default="{ row }">
                <div class="title__main">{{ row.display_title || '-' }}</div>
                <div class="title__sub">{{ row.original_title || '' }}</div>
              </template>
            </el-table-column>
            <el-table-column prop="year" label="年" width="70" />
            <el-table-column prop="status" label="状态" width="160" />
            <el-table-column label="expires_at" width="170">
              <template #default="{ row }">{{ fmtTime(row.expires_at || null) }}</template>
            </el-table-column>
            <el-table-column label="fail" width="70">
              <template #default="{ row }">{{ row.fail_count || 0 }}</template>
            </el-table-column>
            <el-table-column label="操作" :width="isMobile ? 120 : 280" :fixed="isMobile ? false : 'right'">
              <template #default="{ row }">
                <div class="op">
                  <el-button size="small" @click="openDrawer(row)">详情</el-button>
                  <template v-if="!isMobile">
                    <el-button size="small" :disabled="!canWrite" @click="refreshRow(row)">刷新</el-button>
                    <el-button size="small" :disabled="!canWrite" @click="openTTLDialog(row)">TTL</el-button>
                    <el-button size="small" type="danger" :disabled="!canWrite" @click="openDeleteDialog(row)">删除</el-button>
                  </template>
                  <el-dropdown v-else trigger="click">
                    <el-button size="small">更多</el-button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item :disabled="!canWrite" @click="refreshRow(row)">刷新</el-dropdown-item>
                        <el-dropdown-item :disabled="!canWrite" @click="openTTLDialog(row)">TTL</el-dropdown-item>
                        <el-dropdown-item :disabled="!canWrite" @click="openDeleteDialog(row)">删除</el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </div>
              </template>
            </el-table-column>
          </el-table>

          <div class="pager">
            <el-pagination
              background
              layout="prev, pager, next, sizes, total"
              :page-size="list.pageSize"
              :page-sizes="[10, 20, 50, 100, 200]"
              :current-page="list.page"
              :total="list.total"
              @update:page-size="(v) => ((list.pageSize = v), (list.page = 1), loadList())"
              @update:current-page="(v) => ((list.page = v), loadList())"
            />
          </div>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="工具" name="tools">
        <el-card class="card" shadow="never">
          <div class="section">
            <div class="section__title">刷新任务关联缓存</div>
            <div class="section__desc">从任务中提取已关联的 TMDB 条目并刷新其详情缓存。</div>
            <div class="tool-grid">
              <div class="tool-field tool-field--check">
                <el-checkbox v-model="tools.enabledOnly">仅启用任务</el-checkbox>
              </div>
              <div class="tool-field">
                <div class="tool-field__label">最多条目</div>
                <el-input-number v-model="tools.maxItems" :min="1" :max="2000" />
              </div>
              <div class="tool-field tool-field--check">
                <el-checkbox v-model="tools.force">强制刷新</el-checkbox>
              </div>
              <div class="tool-field tool-field--action">
                <el-button type="primary" :loading="tools.refreshingLinked" :disabled="!canWrite" @click="runRefreshLinkedTasks">执行</el-button>
              </div>
            </div>
          </div>

          <el-divider />

          <div class="section">
            <div class="section__title">清理冷数据</div>
            <div class="section__desc">删除长期未访问的缓存条目（保留近 N 天）。</div>
            <div class="tool-grid">
              <div class="tool-field">
                <div class="tool-field__label">保留天数</div>
                <el-input-number v-model="tools.retentionDays" :min="1" :max="3650" />
              </div>
              <div class="tool-field tool-field--action">
                <el-button type="danger" :loading="tools.purging" :disabled="!canWrite" @click="runPurge">清理</el-button>
              </div>
            </div>
          </div>

          <el-divider />

          <div class="section">
            <div class="section__title">快速定位（按 tmdb_id）</div>
            <div class="section__desc">用于排查单个条目的缓存状态，支持查询与强制刷新。</div>
            <div class="tool-grid">
              <div class="tool-field">
                <div class="tool-field__label">类型</div>
                <el-select v-model="quick.mediaType" style="width: 160px">
                  <el-option label="tv" value="tv" />
                  <el-option label="movie" value="movie" />
                </el-select>
              </div>
              <div class="tool-field">
                <div class="tool-field__label">tmdb_id</div>
                <el-input-number v-model="quick.tmdbId" :min="1" :step="1" />
              </div>
              <div class="tool-field tool-field--action">
                <el-button :loading="quick.loading" @click="quickQuery">查询</el-button>
                <el-button type="primary" :loading="quick.loading" :disabled="!canWrite" @click="quickRefresh">强刷</el-button>
              </div>
            </div>
            <div v-if="quick.status" class="mini">
              <div>configured：{{ quick.status.configured ? 'true' : 'false' }} / exists：{{ quick.status.exists ? 'true' : 'false' }}</div>
              <div v-if="quick.status.display_title">标题：{{ quick.status.display_title }}（{{ quick.status.year || '-' }}）</div>
              <div v-if="quick.status.expires_at">expires_at：{{ fmtTime(quick.status.expires_at) }}</div>
              <div v-if="quick.status.last_error">last_error：{{ quick.status.last_error }}</div>
            </div>
          </div>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="定时刷新" name="scheduler">
        <el-card class="card" shadow="never">
          <div class="card__header card__header--flat">
            <div class="section__title">定时刷新设置</div>
            <div class="card__headerRight">
              <el-button text :loading="scheduler.loading" @click="loadScheduler">刷新</el-button>
              <el-button type="primary" :loading="scheduler.saving" :disabled="!canWrite" @click="saveScheduler">保存</el-button>
            </div>
          </div>

          <el-form label-position="top" :disabled="scheduler.loading">
            <el-form-item label="启用">
              <el-switch v-model="scheduler.data.enabled" :disabled="!canWrite" />
            </el-form-item>
            <div class="form__row">
              <el-form-item label="crontab">
                <el-input v-model="scheduler.data.crontab" placeholder="0 */6 * * *" />
              </el-form-item>
              <el-form-item label="timezone">
                <el-input v-model="scheduler.data.timezone" placeholder="Asia/Shanghai" />
              </el-form-item>
            </div>
            <div class="form__row">
              <el-form-item label="每次最多刷新条目">
                <el-input-number v-model="scheduler.data.max_items_per_run" :min="1" :max="2000" />
              </el-form-item>
              <el-form-item label="仅刷新任务关联条目">
                <el-switch v-model="scheduler.data.only_refresh_linked_tasks" :disabled="!canWrite" />
              </el-form-item>
            </div>
            <el-form-item label="冷数据保留天数">
              <el-input-number v-model="scheduler.data.retention_days" :min="1" :max="3650" />
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-drawer v-model="drawer.visible" title="缓存详情" :size="isMobile ? '100%' : '720px'">
      <div v-if="!drawer.row" class="mini">未选择条目</div>
      <div v-else>
        <div class="detail__title">
          <div class="detail__name">{{ drawer.row.display_title || '-' }}</div>
          <div class="detail__meta">{{ drawer.row.media_type }}:{{ drawer.row.tmdb_id }}</div>
        </div>
        <div class="detail__actions">
          <el-button size="small" :disabled="!canWrite" @click="refreshRow(drawer.row)">强制刷新</el-button>
          <el-button size="small" :disabled="!canWrite" @click="openTTLDialog(drawer.row)">设置 TTL</el-button>
          <el-button size="small" type="danger" :disabled="!canWrite" @click="openDeleteDialog(drawer.row)">删除</el-button>
        </div>

        <el-divider />

        <el-tabs v-model="drawer.tab">
          <el-tab-pane label="状态" name="status">
            <div v-if="drawer.loading" class="mini">加载中...</div>
            <div v-else-if="drawer.status" class="kv">
              <div class="kv__row"><div class="kv__k">configured</div><div class="kv__v">{{ drawer.status.configured ? 'true' : 'false' }}</div></div>
              <div class="kv__row"><div class="kv__k">exists</div><div class="kv__v">{{ drawer.status.exists ? 'true' : 'false' }}</div></div>
              <div class="kv__row"><div class="kv__k">fetched_at</div><div class="kv__v">{{ fmtTime(drawer.status.fetched_at || null) }}</div></div>
              <div class="kv__row"><div class="kv__k">expires_at</div><div class="kv__v">{{ fmtTime(drawer.status.expires_at || null) }}</div></div>
              <div class="kv__row"><div class="kv__k">last_accessed_at</div><div class="kv__v">{{ fmtTime(drawer.status.last_accessed_at || null) }}</div></div>
              <div class="kv__row"><div class="kv__k">refresh_in_progress</div><div class="kv__v">{{ drawer.status.refresh_in_progress ? 'true' : 'false' }}</div></div>
              <div class="kv__row"><div class="kv__k">fail_count</div><div class="kv__v">{{ drawer.status.fail_count || 0 }}</div></div>
              <div v-if="drawer.status.last_error" class="kv__row">
                <div class="kv__k">last_error</div>
                <div class="kv__v kv__v--error">{{ drawer.status.last_error }}</div>
              </div>
            </div>
          </el-tab-pane>
          <el-tab-pane label="缓存数据" name="payload">
            <div class="payload__actions">
              <el-button size="small" :loading="drawer.payloadLoading" @click="loadDrawerPayload">加载</el-button>
              <el-button size="small" :disabled="!drawerPayloadRaw" @click="copyDrawerPayloadRaw">复制原始</el-button>
              <el-button size="small" :disabled="!drawerPayloadRaw" @click="downloadDrawerPayload">下载</el-button>
              <el-tag v-if="drawer.payloadItem?.update_weekdays?.length" type="info">
                更新星期：{{ drawer.payloadItem?.update_weekdays?.join(',') }}
              </el-tag>
            </div>
            <el-alert
              v-if="drawerPayloadTooLarge"
              class="payload__alert"
              title="缓存数据过大：仅展示截断预览以避免页面卡死"
              type="warning"
              show-icon
              :closable="false"
            />
            <div v-if="drawer.payloadLoading" class="mini">加载中...</div>
            <div v-else-if="drawer.status && !drawer.status.exists" class="mini">未找到缓存条目（可能尚未写入缓存）</div>
            <div v-else-if="drawerPayloadText" class="payload__box">
              <div class="payload__meta">大小：{{ drawerPayloadSize }} 字符</div>
              <pre class="payload__pre">{{ drawerPayloadText }}</pre>
            </div>
            <div v-else class="mini">无缓存数据</div>
          </el-tab-pane>
        </el-tabs>
      </div>
    </el-drawer>

    <el-dialog v-model="ttlDialog.visible" title="设置 TTL" width="460px">
      <el-form label-position="top">
        <el-form-item label="目标">
          <div class="mini">{{ ttlDialog.mediaType }}:{{ ttlDialog.tmdbId }}</div>
        </el-form-item>
        <div class="ttl__row">
          <el-form-item label="数值">
            <el-input-number v-model="ttlDialog.value" :min="1" :max="3650" />
          </el-form-item>
          <el-form-item label="单位">
            <el-select v-model="ttlDialog.unit" style="width: 160px">
              <el-option label="分钟" value="minute" />
              <el-option label="小时" value="hour" />
              <el-option label="天" value="day" />
            </el-select>
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="ttlDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="ttlDialog.submitting" :disabled="!canWrite" @click="submitTTL">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="deleteDialog.visible"
      title="删除缓存"
      width="560px"
      :close-on-click-modal="false"
      @close="closeDeleteDialog"
    >
      <div v-if="deleteDialog.row" class="del">
        <el-alert type="warning" show-icon :closable="false" class="del__alert">
          <template #title>删除的是“TMDB 详情缓存”</template>
          <template #default>
            <div class="del__text">不影响 TMDB 配置；下次访问详情接口会重新写入缓存。</div>
          </template>
        </el-alert>

        <el-descriptions :column="1" border>
          <el-descriptions-item label="条目">
            <el-tag>{{ deleteDialog.row.media_type }}</el-tag>
            <span class="del__id">{{ deleteDialog.row.tmdb_id }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="标题">
            <div class="del__title">
              <div>{{ deleteDialog.row.display_title || '-' }}</div>
              <div class="del__sub">{{ deleteDialog.row.original_title || '' }}</div>
            </div>
          </el-descriptions-item>
          <el-descriptions-item label="有效期">
            <div class="del__time">
              <div>fetched_at：{{ fmtTime(deleteDialog.row.fetched_at || null) }}</div>
              <div>expires_at：{{ fmtTime(deleteDialog.row.expires_at || null) }}</div>
              <div>last_accessed_at：{{ fmtTime(deleteDialog.row.last_accessed_at || null) }}</div>
            </div>
          </el-descriptions-item>
        </el-descriptions>
      </div>

      <template #footer>
        <el-button :disabled="deleteDialog.deleting" @click="closeDeleteDialog">取消</el-button>
        <el-button
          type="danger"
          :loading="deleteDialog.deleting"
          :disabled="!canWrite"
          @click="confirmDelete"
        >
          删除
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="actionDialog.visible" width="520px" :show-close="false" :close-on-click-modal="true">
      <el-result :icon="actionDialog.icon" :title="actionDialog.title" :sub-title="actionDialog.subTitle">
        <template #extra>
          <div v-if="Object.keys(actionDialog.meta || {}).length" class="action__meta">
            <el-descriptions :column="1" border>
              <el-descriptions-item v-for="(v, k) in actionDialog.meta" :key="k" :label="String(k)">{{ String(v) }}</el-descriptions-item>
            </el-descriptions>
          </div>
          <div class="action__actions">
            <el-button type="primary" @click="actionDialog.visible = false">知道了</el-button>
          </div>
        </template>
      </el-result>
    </el-dialog>
  </div>
</template>

<style scoped>
.page {
  padding: 16px;
}
.page__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.page__title {
  font-size: 18px;
  font-weight: 600;
}
.page__actions {
  display: flex;
  gap: 8px;
}
.page__alert {
  margin-bottom: 12px;
}
.tabs {
  margin-bottom: 12px;
}
.tabs__extra {
  display: flex;
  align-items: center;
  gap: 10px;
}
.card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.card__header--flat {
  margin-bottom: 12px;
}
.card__headerRight {
  display: flex;
  gap: 10px;
  align-items: center;
}
.form__row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.section__title {
  font-weight: 600;
}
.section__desc {
  margin-top: 6px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.section + .section {
  margin-top: 14px;
}
.tool-grid {
  margin-top: 10px;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  align-items: end;
}
.tool-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.tool-field__label {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.2;
}
.tool-field--check {
  justify-content: flex-end;
}
.tool-field--action {
  flex-direction: row;
  align-items: center;
  gap: 10px;
  justify-content: flex-end;
}
.filters {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
.title__main {
  font-weight: 500;
}
.title__sub {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.op {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.mini {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.6;
}
.detail__title {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
}
.detail__name {
  font-size: 16px;
  font-weight: 600;
}
.detail__meta {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.detail__actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 10px;
}
.kv {
  display: grid;
  gap: 8px;
}
.kv__row {
  display: grid;
  grid-template-columns: 160px 1fr;
  gap: 10px;
}
.kv__k {
  color: var(--el-text-color-secondary);
}
.kv__v--error {
  color: var(--el-color-danger);
  word-break: break-word;
}
.payload__actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.payload__alert {
  margin-bottom: 10px;
}
.payload__box {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 16px;
  background: var(--el-fill-color-blank);
  overflow: hidden;
}
.payload__meta {
  padding: 10px 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.payload__pre {
  margin: 0;
  padding: 12px;
  white-space: pre-wrap;
  font-size: 12px;
  line-height: 1.5;
  max-height: 65vh;
  overflow: auto;
}
.ttl__row {
  display: grid;
  grid-template-columns: 1fr 160px;
  gap: 12px;
}
.del__alert {
  margin-bottom: 12px;
}
.del__text {
  color: var(--el-text-color-regular);
}
.del__id {
  margin-left: 8px;
  font-weight: 600;
}
.del__title {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.del__sub {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.del__time {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.action__meta {
  width: 100%;
  margin-top: 12px;
}
.action__actions {
  display: flex;
  justify-content: center;
  margin-top: 14px;
}
@media (max-width: 960px) {
  .form__row {
    grid-template-columns: 1fr;
  }
  .tool-grid {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 767px) {
  .tool-grid {
    grid-template-columns: 1fr;
  }
  .ttl__row {
    grid-template-columns: 1fr;
  }

  .kv__row {
    grid-template-columns: 1fr;
  }
}
</style>
