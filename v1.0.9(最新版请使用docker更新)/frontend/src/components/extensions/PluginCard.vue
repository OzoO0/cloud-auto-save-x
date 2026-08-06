<script setup lang="ts">
import type { TagProps } from 'element-plus'

import type { PluginItem } from '@/types/extensions'

const props = defineProps<{
  plugin: PluginItem
  canWrite: boolean
}>()

const emit = defineEmits<{
  configure: [plugin: PluginItem]
  toggle: [plugin: PluginItem, enabled: boolean]
}>()

const runtimeTag = computed<TagProps['type']>(() => {
  if (props.plugin.runtime_status === 'active') return 'success'
  if (props.plugin.runtime_status === 'error') return 'danger'
  return 'info'
})

const configSummary = computed(() => {
  if (!props.plugin.config_fields?.length) return []
  return props.plugin.config_fields
    .map((field) => {
      const value = props.plugin.config?.[field.key]
      if (value === undefined || value === null || value === '') return null
      return `${field.label || field.key}: ${typeof value === 'boolean' ? (value ? '开启' : '关闭') : String(value)}`
    })
    .filter((item): item is string => Boolean(item))
    .slice(0, 3)
})
</script>

<template>
  <article class="glass-panel plugin-card" @click="emit('configure', plugin)">
    <div class="plugin-card__header">
      <div class="plugin-card__heading">
        <h3 :title="plugin.plugin_key">{{ plugin.plugin_key }}</h3>
        <div class="plugin-card__meta">{{ plugin.module_name }} · {{ plugin.source_type }}</div>
      </div>
      <el-switch
        v-if="canWrite"
        class="plugin-card__switch"
        :model-value="plugin.enabled"
        @click.stop
        @change="emit('toggle', plugin, Boolean($event))"
      />
    </div>

    <div class="plugin-card__status">
      <el-tag :type="plugin.enabled ? 'success' : 'info'" effect="plain" round size="small">
        {{ plugin.enabled ? '启用' : '禁用' }}
      </el-tag>
      <el-tag :type="runtimeTag" effect="plain" round size="small">
        {{ plugin.runtime_status || '未加载' }}
      </el-tag>
      <span class="status-pill plugin-card__priority">优先级 {{ plugin.priority }}</span>
    </div>

    <div class="plugin-card__body">
      <div class="plugin-card__body-title">配置摘要</div>
      <template v-if="configSummary.length">
        <div v-for="summary in configSummary" :key="summary" class="plugin-card__summary" :title="summary">
          {{ summary }}
        </div>
      </template>
      <div v-else class="plugin-card__summary plugin-card__summary--muted">暂无结构化配置摘要</div>
      <div v-if="plugin.last_error" class="plugin-card__error" :title="plugin.last_error">{{ plugin.last_error }}</div>
    </div>

    <div class="plugin-card__footer">
      <span class="plugin-card__hint">点击卡片可直接配置</span>
      <el-button type="primary" text bg @click.stop="emit('configure', plugin)">配置</el-button>
    </div>
  </article>
</template>

<style scoped>
.plugin-card {
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-height: 280px;
  padding: 22px;
  cursor: pointer;
  transition:
    transform 0.2s ease,
    box-shadow 0.2s ease,
    border-color 0.2s ease,
    background-color 0.2s ease;
}

.plugin-card:hover {
  transform: translateY(-2px);
  border-color: rgba(59, 130, 246, 0.24);
  box-shadow: var(--panel-shadow-hover);
}

.plugin-card__header,
.plugin-card__footer {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.plugin-card__heading {
  min-width: 0;
  flex: 1;
}

.plugin-card__switch {
  flex-shrink: 0;
}

.plugin-card h3 {
  margin: 0;
  overflow: hidden;
  font-size: 18px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.plugin-card__meta,
.plugin-card__priority,
.plugin-card__summary--muted,
.plugin-card__hint {
  color: var(--el-text-color-secondary);
}

.plugin-card__meta {
  margin-top: 6px;
  overflow: hidden;
  font-size: 13px;
  line-height: 1.5;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.plugin-card__status {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.plugin-card__body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  flex: 1;
}

.plugin-card__body-title {
  margin-bottom: 2px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--el-text-color-secondary);
}

.plugin-card__summary,
.plugin-card__error {
  display: -webkit-box;
  overflow: hidden;
  font-size: 13px;
  line-height: 1.5;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.plugin-card__summary {
  padding: 10px 12px;
  border-radius: 14px;
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
}

.plugin-card__error {
  margin-top: auto;
  padding: 10px 12px;
  border-radius: 14px;
  background: rgba(239, 68, 68, 0.14);
  border: 1px solid rgba(239, 68, 68, 0.22);
  color: var(--el-color-danger);
}

.plugin-card__hint {
  font-size: 12px;
  line-height: 1.4;
}

@media (max-width: 768px) {
  .plugin-card {
    min-height: auto;
    padding: 18px;
  }

  .plugin-card__footer {
    align-items: center;
  }
}
</style>
