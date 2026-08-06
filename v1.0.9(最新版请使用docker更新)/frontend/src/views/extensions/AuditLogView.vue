<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { fetchAuditLogs } from '@/api/audit'
import type { AuditLogItem } from '@/types/audit'
import { useIsMobile } from '@/composables/useIsMobile'

const loading = ref(false)
const items = ref<AuditLogItem[]>([])
const total = ref(0)
const isMobile = useIsMobile()

const query = reactive({
  page: 1,
  page_size: 20,
  q: '',
  action: '',
  success: 'all' as 'all' | 'success' | 'failed',
})

const successParam = computed(() => {
  if (query.success === 'success') return true
  if (query.success === 'failed') return false
  return undefined
})

async function loadData() {
  loading.value = true
  try {
    const data = await fetchAuditLogs({
      page: query.page,
      page_size: query.page_size,
      q: query.q || undefined,
      action: query.action || undefined,
      success: successParam.value,
    })
    items.value = data.items || []
    total.value = data.total || 0
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  query.q = ''
  query.action = ''
  query.success = 'all'
  query.page = 1
  loadData()
}

onMounted(loadData)
</script>

<template>
  <div class="shell-page">
    <div class="section-header">
      <div class="section-header__title">
        <h2>审计日志</h2>
      </div>
      <div class="toolbar__right">
        <el-button type="primary" @click="loadData">刷新</el-button>
      </div>
    </div>

    <section class="glass-panel filter-strip">
      <div class="toolbar">
        <div class="toolbar__left">
          <el-input
            v-model="query.q"
            clearable
            placeholder="搜索 action / 用户 / 目标 / detail"
            :style="{ width: isMobile ? '100%' : '300px' }"
            @keyup.enter="loadData"
            @clear="loadData"
          />
          <el-input
            v-model="query.action"
            clearable
            placeholder="精确 action（可选）"
            :style="{ width: isMobile ? '100%' : '240px' }"
            @keyup.enter="loadData"
            @clear="loadData"
          />
          <el-segmented
            v-model="query.success"
            :options="[
              { label: '全部', value: 'all' },
              { label: '成功', value: 'success' },
              { label: '失败', value: 'failed' },
            ]"
          />
        </div>
        <div class="toolbar__right">
          <el-button @click="resetFilters">清空筛选</el-button>
        </div>
      </div>
    </section>

    <section class="glass-panel table-panel">
      <el-table :data="items" border v-loading="loading">
        <el-table-column prop="created_at" label="时间" min-width="180" />
        <el-table-column label="用户" min-width="140">
          <template #default="{ row }">
            <span>{{ row.actor_username || (row.actor_user_id ? `#${row.actor_user_id}` : '-') }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="action" label="Action" min-width="220" />
        <el-table-column label="目标" min-width="200">
          <template #default="{ row }">
            <span>{{ row.target_type || '-' }}</span>
            <span v-if="row.target_id" class="muted">:{{ row.target_id }}</span>
          </template>
        </el-table-column>
        <el-table-column label="结果" width="100">
          <template #default="{ row }">
            <el-tag :type="row.success ? 'success' : 'danger'" effect="plain" round>
              {{ row.success ? '成功' : '失败' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="ip" label="IP" width="140" />
        <el-table-column prop="detail" label="Detail" min-width="320" show-overflow-tooltip />
      </el-table>

      <div class="pagination-bar">
        <el-pagination
          v-model:current-page="query.page"
          v-model:page-size="query.page_size"
          background
          layout="total, sizes, prev, pager, next"
          :total="total"
          @change="loadData"
        />
      </div>
    </section>
  </div>
</template>

<style scoped>
.table-panel {
  padding: 18px;
}

.muted {
  color: var(--el-text-color-secondary);
}

.pagination-bar {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>

