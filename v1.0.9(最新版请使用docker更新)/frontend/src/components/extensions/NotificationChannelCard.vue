<script setup lang="ts">
import type { TagProps } from 'element-plus'

export type NotifyField = {
  key: string
  label?: string
  placeholder?: string
  input?: 'text' | 'textarea' | 'password' | 'switch' | 'number'
  rows?: number
}

export type NotifyChannel = {
  id: string
  title: string
  fields: NotifyField[]
  required_keys: string[]
  summary_keys: string[]
}

const props = defineProps<{
  channel: NotifyChannel
  config: Record<string, any>
  enabled: boolean
  canWrite: boolean
  configured?: boolean
  lastResult?: { ok: boolean; error?: string | null } | null
}>()

const emit = defineEmits<{
  configure: [channel: NotifyChannel]
  toggle: [channel: NotifyChannel, enabled: boolean]
}>()

function hasValue(value: any) {
  if (typeof value === 'boolean') return value
  if (typeof value === 'number') return !Number.isNaN(value) && value !== 0
  return String(value ?? '').trim() !== ''
}

function maskValue(value: any) {
  const text = String(value ?? '').trim()
  if (!text) return ''
  if (text.length <= 6) return '******'
  return `${text.slice(0, 2)}******${text.slice(-2)}`
}

const configured = computed(() => {
  if (typeof props.configured === 'boolean') return props.configured
  return props.channel.required_keys.every((key) => hasValue(props.config?.[key]))
})

const configSummary = computed(() => {
  const keys = props.channel.summary_keys.length ? props.channel.summary_keys : props.channel.required_keys
  return keys
    .map((key) => {
      const value = props.config?.[key]
      if (!hasValue(value)) return null
      const shouldMask = /token|secret|password|_key$|key/i.test(key)
      return `${key}: ${shouldMask ? maskValue(value) : String(value)}`
    })
    .filter((item): item is string => Boolean(item))
    .slice(0, 3)
})

const statusTag = computed<TagProps['type']>(() => {
  if (!configured.value) return 'info'
  if (!props.enabled) return 'warning'
  return 'success'
})

const statusLabel = computed(() => {
  if (!configured.value) return '未配置'
  return props.enabled ? '已启用' : '已停用'
})
</script>

<template>
  <article class="glass-panel channel-card" @click="emit('configure', channel)">
    <div class="channel-card__header">
      <div class="channel-card__heading">
        <h3 :title="channel.title">{{ channel.title }}</h3>
        <div class="channel-card__meta">{{ channel.id }}</div>
      </div>
      <el-switch
        v-if="canWrite"
        class="channel-card__switch"
        :model-value="enabled"
        :disabled="!configured"
        @click.stop
        @change="emit('toggle', channel, Boolean($event))"
      />
    </div>

    <div class="channel-card__status">
      <el-tag :type="statusTag" effect="plain" round size="small">
        {{ statusLabel }}
      </el-tag>
      <el-tag v-if="lastResult" :type="lastResult.ok ? 'success' : 'danger'" effect="plain" round size="small">
        {{ lastResult.ok ? '最近测试成功' : '最近测试失败' }}
      </el-tag>
    </div>

    <div class="channel-card__body">
      <div class="channel-card__body-title">重要信息</div>
      <template v-if="configSummary.length">
        <div v-for="summary in configSummary" :key="summary" class="channel-card__summary" :title="summary">
          {{ summary }}
        </div>
      </template>
      <div v-else class="channel-card__summary channel-card__summary--muted">点击配置以填写参数</div>
      <div v-if="lastResult && !lastResult.ok && lastResult.error" class="channel-card__error" :title="String(lastResult.error)">
        {{ lastResult.error }}
      </div>
    </div>

    <div class="channel-card__footer">
      <span class="channel-card__hint">点击卡片可配置</span>
      <div class="channel-card__actions">
        <el-button type="primary" text bg @click.stop="emit('configure', channel)">配置</el-button>
      </div>
    </div>
  </article>
</template>

<style scoped>
.channel-card {
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-height: 260px;
  padding: 22px;
  cursor: pointer;
  transition:
    transform 0.2s ease,
    box-shadow 0.2s ease,
    border-color 0.2s ease,
    background-color 0.2s ease;
}

.channel-card:hover {
  transform: translateY(-2px);
  border-color: rgba(59, 130, 246, 0.24);
  box-shadow: var(--panel-shadow-hover);
}

.channel-card__header,
.channel-card__footer {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.channel-card__heading {
  min-width: 0;
  flex: 1;
}

.channel-card__switch {
  flex-shrink: 0;
}

.channel-card h3 {
  margin: 0;
  overflow: hidden;
  font-size: 18px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.channel-card__meta,
.channel-card__summary--muted,
.channel-card__hint {
  color: var(--el-text-color-secondary);
}

.channel-card__meta {
  margin-top: 6px;
  overflow: hidden;
  font-size: 13px;
  line-height: 1.5;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.channel-card__status {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.channel-card__body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  flex: 1;
}

.channel-card__body-title {
  margin-bottom: 2px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--el-text-color-secondary);
}

.channel-card__summary,
.channel-card__error {
  display: -webkit-box;
  overflow: hidden;
  font-size: 13px;
  line-height: 1.5;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.channel-card__summary {
  padding: 10px 12px;
  border-radius: 14px;
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
}

.channel-card__error {
  margin-top: auto;
  padding: 10px 12px;
  border-radius: 14px;
  background: rgba(239, 68, 68, 0.14);
  border: 1px solid rgba(239, 68, 68, 0.22);
  color: var(--el-color-danger);
}

.channel-card__hint {
  font-size: 12px;
  line-height: 1.4;
}

.channel-card__actions {
  display: inline-flex;
  gap: 8px;
  align-items: center;
}

@media (max-width: 768px) {
  .channel-card {
    min-height: auto;
    padding: 18px;
  }

  .channel-card__footer {
    align-items: center;
  }
}
</style>
