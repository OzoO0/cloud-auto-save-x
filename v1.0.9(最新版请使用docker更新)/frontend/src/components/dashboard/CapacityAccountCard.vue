<script setup lang="ts">
import type { TagProps } from 'element-plus'

import type { DriveAccountItem } from '@/types/extensions'
import { formatBytes, formatDateTime, formatPercent } from '@/utils/capacity'

const props = withDefaults(
  defineProps<{
    account: DriveAccountItem
    compact?: boolean
  }>(),
  {
    compact: false,
  },
)

const usagePercent = computed(() => Math.round((props.account.usage_ratio || 0) * 100))
const thresholdRatio = computed(() => props.account.capacity_warning_threshold / 100)

const capacityState = computed<'unknown' | 'safe' | 'warning'>(() => {
  if (props.account.usage_ratio === null || props.account.usage_ratio === undefined) return 'unknown'
  return props.account.usage_ratio >= thresholdRatio.value ? 'warning' : 'safe'
})

const runtimeTag = computed<TagProps['type']>(() => {
  if (props.account.runtime_status === 'active') return 'success'
  if (props.account.runtime_status === 'error') return 'danger'
  return 'info'
})
</script>

<template>
  <article class="glass-panel account-card" :class="{ 'account-card--compact': compact }">
    <div class="account-card__header">
      <div>
        <div class="account-card__title-row">
          <h3>{{ account.name }}</h3>
          <el-tag v-if="account.is_default" type="success" effect="plain" round>默认账号</el-tag>
        </div>
        <div class="account-card__meta">
          <span>{{ account.profile?.nickname || account.profile?.username || '未命名账号' }}</span>
          （
          <span>{{ account.profile?.drive_name || account.drive_type }}</span>
          ）
        </div>
      </div>

      <div class="account-card__status">
        <el-tag :type="account.enabled ? 'success' : 'info'" effect="plain" round>
          {{ account.enabled ? '启用' : '禁用' }}
        </el-tag>
        <el-tag :type="runtimeTag" effect="plain" round>
          {{ account.runtime_status || '未探测' }}
        </el-tag>
      </div>
    </div>

    <div class="account-card__capacity">
      <template v-if="capacityState !== 'unknown'">
        <div class="account-card__capacity-main">
          <span>{{ formatBytes(account.used_space) }}</span>
          <span class="account-card__capacity-total">/ {{ formatBytes(account.total_space) }}</span>
        </div>
        <div class="account-card__capacity-side">
          <span class="account-card__percent">{{ formatPercent(account.usage_ratio) }}</span>
          <span :class="['status-pill', capacityState === 'warning' ? 'status-pill--danger' : 'status-pill--success']">
            阈值 {{ account.capacity_warning_threshold }}%
          </span>
        </div>
        <el-progress
          :percentage="usagePercent"
          :stroke-width="compact ? 8 : 10"
          :show-text="false"
          :status="capacityState === 'warning' ? 'exception' : 'success'"
        />
      </template>
      <template v-else>
        <div class="account-card__empty">该账号暂未获得容量数据，可先执行探测或等待适配器补充支持。</div>
      </template>
    </div>

    <div class="account-card__footer">
      <span>最近刷新：{{ formatDateTime(account.profile_updated_at || account.last_checked_at) }}</span>
      <span v-if="account.last_error" class="account-card__error">{{ account.last_error }}</span>
    </div>

    <div v-if="$slots.actions" class="account-card__actions">
      <slot name="actions" />
    </div>
  </article>
</template>

<style scoped>
.account-card__actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}
</style>
