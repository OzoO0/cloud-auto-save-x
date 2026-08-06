<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  clearInvalidShareLinks,
  clearSharePreviewBatchMemoryCache,
  deleteInvalidShareLink,
  deleteSharePreviewBatchCacheItem,
  fetchInvalidShareLinksList,
  fetchSharePreviewBatchCacheList,
  purgeSharePreviewBatchCache,
} from '@/api/shareLinkCache'
import { useIsMobile } from '@/composables/useIsMobile'
import { TASK_WRITE } from '@/constants/permissions'
import { useAuthStore } from '@/stores/auth'
import type { InvalidShareLinkListItem, SharePreviewBatchCacheListItem } from '@/types/shareLinkCache'

const auth = useAuthStore()
const isMobile = useIsMobile()
const canWrite = computed(() => auth.permissions.includes(TASK_WRITE))

const activeTab = ref<'cache' | 'invalid'>('cache')

const cache = reactive({
  loading: false,
  items: [] as SharePreviewBatchCacheListItem[],
  total: 0,
  query: {
    page: 1,
    page_size: 20,
    q: '',
    drive_type: '',
    ok: 'all' as 'all' | 'ok' | 'fail',
    expired_only: false,
  },
})

const invalid = reactive({
  loading: false,
  items: [] as InvalidShareLinkListItem[],
  total: 0,
  query: {
    page: 1,
    page_size: 20,
    q: '',
    drive_type: '',
  },
})

const cacheOkParam = computed(() => {
  if (cache.query.ok === 'ok') return true
  if (cache.query.ok === 'fail') return false
  return undefined
})

async function loadCache() {
  cache.loading = true
  try {
    const data = await fetchSharePreviewBatchCacheList({
      page: cache.query.page,
      page_size: cache.query.page_size,
      q: cache.query.q || undefined,
      drive_type: cache.query.drive_type || undefined,
      ok: cacheOkParam.value,
      expired_only: cache.query.expired_only || undefined,
    })
    cache.items = data.items || []
    cache.total = data.total || 0
  } finally {
    cache.loading = false
  }
}

async function loadInvalid() {
  invalid.loading = true
  try {
    const data = await fetchInvalidShareLinksList({
      page: invalid.query.page,
      page_size: invalid.query.page_size,
      q: invalid.query.q || undefined,
      drive_type: invalid.query.drive_type || undefined,
    })
    invalid.items = data.items || []
    invalid.total = data.total || 0
  } finally {
    invalid.loading = false
  }
}

async function refreshActive() {
  if (activeTab.value === 'invalid') {
    await loadInvalid()
  } else {
    await loadCache()
  }
}

async function handleDeleteCacheItem(shareurl: string) {
  if (!canWrite.value) return
  const out = await deleteSharePreviewBatchCacheItem({ shareurl })
  ElMessage.success(`已删除 ${out.deleted || 0} 条`)
  await loadCache()
}

async function handleDeleteInvalidItem(shareurl: string) {
  if (!canWrite.value) return
  const out = await deleteInvalidShareLink({ shareurl })
  ElMessage.success(`已删除 ${out.deleted || 0} 条`)
  await loadInvalid()
}

async function handlePurgeExpired() {
  if (!canWrite.value) return
  const out = await purgeSharePreviewBatchCache({ expired_only: true, retention_seconds: 0 })
  ElMessage.success(`已清理 ${out.deleted || 0} 条过期缓存`)
  await loadCache()
}

async function handlePurgeRetention() {
  if (!canWrite.value) return
  const out = await purgeSharePreviewBatchCache({ expired_only: false, retention_seconds: 0 })
  ElMessage.success(`已清理 ${out.deleted || 0} 条历史缓存`)
  await loadCache()
}

async function handleClearMemoryCache() {
  if (!canWrite.value) return
  const out = await clearSharePreviewBatchMemoryCache()
  if (out.cleared) ElMessage.success('已清空进程内缓存（仅对当前后端进程生效）')
}

async function handleClearInvalidAll() {
  if (!canWrite.value) return
  await ElMessageBox.confirm('确认清空所有“永久异常 shareurl”？这会影响资源搜索/修复的失效过滤。', '清空确认', {
    type: 'warning',
    confirmButtonText: '清空',
    cancelButtonText: '取消',
  })
  const out = await clearInvalidShareLinks({})
  ElMessage.success(`已清空 ${out.deleted || 0} 条`)
  await loadInvalid()
}

function resetCacheFilters() {
  cache.query.q = ''
  cache.query.drive_type = ''
  cache.query.ok = 'all'
  cache.query.expired_only = false
  cache.query.page = 1
  loadCache()
}

function resetInvalidFilters() {
  invalid.query.q = ''
  invalid.query.drive_type = ''
  invalid.query.page = 1
  loadInvalid()
}

onMounted(async () => {
  await loadCache()
  await loadInvalid()
})
</script>

<template>
  <div class="shell-page">
    <div class="section-header">
      <div class="section-header__title">
        <h2>分享链接缓存</h2>
      </div>
      <div class="toolbar__right">
        <el-button type="primary" @click="refreshActive">刷新</el-button>
      </div>
    </div>

    <section class="glass-panel table-panel">
      <el-tabs v-model="activeTab" class="cache-tabs">
        <el-tab-pane label="预览缓存" name="cache">
          <section class="glass-panel filter-strip">
            <div class="toolbar">
              <div class="toolbar__left">
                <el-input
                  v-model="cache.query.q"
                  clearable
                  placeholder="搜索 shareurl"
                  :style="{ width: isMobile ? '100%' : '360px' }"
                  @keyup.enter="loadCache"
                  @clear="loadCache"
                />
                <el-input
                  v-model="cache.query.drive_type"
                  clearable
                  placeholder="drive_type（可选）"
                  :style="{ width: isMobile ? '100%' : '220px' }"
                  @keyup.enter="loadCache"
                  @clear="loadCache"
                />
                <el-segmented
                  v-model="cache.query.ok"
                  :options="[
                    { label: '全部', value: 'all' },
                    { label: '成功', value: 'ok' },
                    { label: '失败', value: 'fail' },
                  ]"
                />
                <el-checkbox v-model="cache.query.expired_only" @change="loadCache">仅过期</el-checkbox>
              </div>
              <div class="toolbar__right">
                <el-button @click="resetCacheFilters">清空筛选</el-button>
                <el-button :disabled="!canWrite" @click="handleClearMemoryCache">清空内存缓存</el-button>
                <el-button :disabled="!canWrite" @click="handlePurgeExpired">清理过期</el-button>
                <el-button :disabled="!canWrite" @click="handlePurgeRetention">清理历史</el-button>
              </div>
            </div>
          </section>

          <el-table :data="cache.items" border v-loading="cache.loading">
            <el-table-column prop="shareurl" label="shareurl" min-width="360" show-overflow-tooltip />
            <el-table-column prop="drive_type" label="drive_type" width="130" />
            <el-table-column label="结果" width="100">
              <template #default="{ row }">
                <el-tag :type="row.ok ? 'success' : 'danger'" effect="plain" round>{{ row.ok ? 'OK' : 'FAIL' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column
              prop="message"
              label="message"
              min-width="220"
              :show-overflow-tooltip="{
                appendTo: 'body',
                popperOptions: { strategy: 'fixed' },
              }"
            />
            <el-table-column prop="checked_at" label="checked_at" width="180" />
            <el-table-column prop="expires_at" label="expires_at" width="180" />
            <el-table-column prop="hit_count" label="hit" width="90" />
            <el-table-column label="操作" width="110" fixed="right">
              <template #default="{ row }">
                <el-button link type="danger" :disabled="!canWrite" @click="handleDeleteCacheItem(row.shareurl)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>

          <div class="pagination-bar">
            <el-pagination
              v-model:current-page="cache.query.page"
              v-model:page-size="cache.query.page_size"
              background
              layout="total, sizes, prev, pager, next"
              :total="cache.total"
              @change="loadCache"
            />
          </div>
        </el-tab-pane>

        <el-tab-pane label="永久异常" name="invalid">
          <section class="glass-panel filter-strip">
            <div class="toolbar">
              <div class="toolbar__left">
                <el-input
                  v-model="invalid.query.q"
                  clearable
                  placeholder="搜索 shareurl"
                  :style="{ width: isMobile ? '100%' : '360px' }"
                  @keyup.enter="loadInvalid"
                  @clear="loadInvalid"
                />
                <el-input
                  v-model="invalid.query.drive_type"
                  clearable
                  placeholder="drive_type（可选）"
                  :style="{ width: isMobile ? '100%' : '220px' }"
                  @keyup.enter="loadInvalid"
                  @clear="loadInvalid"
                />
              </div>
              <div class="toolbar__right">
                <el-button @click="resetInvalidFilters">清空筛选</el-button>
                <el-button type="danger" :disabled="!canWrite" @click="handleClearInvalidAll">清空全部</el-button>
              </div>
            </div>
          </section>

          <el-table :data="invalid.items" border v-loading="invalid.loading">
            <el-table-column prop="shareurl" label="shareurl" min-width="360" show-overflow-tooltip />
            <el-table-column prop="drive_type" label="drive_type" width="130" />
            <el-table-column
              prop="message"
              label="message"
              min-width="220"
              :show-overflow-tooltip="{
                appendTo: 'body',
                popperOptions: { strategy: 'fixed' },
              }"
            />
            <el-table-column prop="hit_count" label="hit" width="90" />
            <el-table-column prop="updated_at" label="updated_at" width="180" />
            <el-table-column label="操作" width="110" fixed="right">
              <template #default="{ row }">
                <el-button link type="danger" :disabled="!canWrite" @click="handleDeleteInvalidItem(row.shareurl)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>

          <div class="pagination-bar">
            <el-pagination
              v-model:current-page="invalid.query.page"
              v-model:page-size="invalid.query.page_size"
              background
              layout="total, sizes, prev, pager, next"
              :total="invalid.total"
              @change="loadInvalid"
            />
          </div>
        </el-tab-pane>
      </el-tabs>
    </section>
  </div>
</template>

<style scoped>
.table-panel {
  padding: 18px;
}

.pagination-bar {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
