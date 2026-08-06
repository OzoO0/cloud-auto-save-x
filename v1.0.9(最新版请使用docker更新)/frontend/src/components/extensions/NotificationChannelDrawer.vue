<script setup lang="ts">
import type { NotifyChannel } from '@/components/extensions/NotificationChannelCard.vue'
import { useIsMobile } from '@/composables/useIsMobile'

type DrawerPayload = {
  channel_id: string
  enabled: boolean
  config_patch: Record<string, any>
}

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    channel?: NotifyChannel | null
    enabled?: boolean
    config?: Record<string, any>
    submitting?: boolean
  }>(),
  {
    channel: null,
    enabled: true,
    config: () => ({}),
    submitting: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  save: [payload: DrawerPayload]
}>()

const state = reactive({
  enabled: true,
  patch: {} as Record<string, any>,
})
const isMobile = useIsMobile()

function cloneConfig<T>(value: T): T {
  return JSON.parse(JSON.stringify(value ?? {}))
}

watch(
  () => [props.modelValue, props.channel] as const,
  ([visible]) => {
    if (!visible || !props.channel) return
    state.enabled = Boolean(props.enabled)
    const patch: Record<string, any> = {}
    for (const field of props.channel.fields) {
      patch[field.key] = cloneConfig((props.config || {})[field.key])
    }
    state.patch = patch
  },
  { immediate: true },
)

function closeDrawer() {
  emit('update:modelValue', false)
}

function submit() {
  if (!props.channel) return
  emit('save', {
    channel_id: props.channel.id,
    enabled: Boolean(state.enabled),
    config_patch: cloneConfig(state.patch),
  })
}
</script>

<template>
  <el-drawer
    :model-value="modelValue"
    :title="channel ? `配置渠道 · ${channel.title}` : '配置渠道'"
    :size="isMobile ? '100%' : '560px'"
    @close="closeDrawer"
  >
    <el-form v-if="channel" label-position="top" class="drawer-form">
      <div class="drawer-form__section">
        <div class="drawer-form__section-title">运行控制</div>
        <div class="drawer-form__switch-row">
          <el-switch v-model="state.enabled" active-text="启用该渠道" inactive-text="停用该渠道" />
        </div>
      </div>

      <div class="drawer-form__section">
        <div class="drawer-form__section-title">渠道配置</div>
        <el-form-item v-for="field in channel.fields" :key="field.key" :label="field.label || field.key">
          <el-switch
            v-if="field.input === 'switch'"
            v-model="state.patch[field.key]"
            active-text="开启"
            inactive-text="关闭"
          />
          <el-input-number v-else-if="field.input === 'number'" v-model="state.patch[field.key]" style="width: 100%" />
          <el-input
            v-else-if="field.input === 'textarea'"
            v-model="state.patch[field.key]"
            type="textarea"
            :rows="field.rows || 4"
            :placeholder="field.placeholder || ''"
          />
          <el-input
            v-else
            v-model="state.patch[field.key]"
            :type="field.input === 'password' ? 'password' : 'text'"
            :show-password="field.input === 'password'"
            :placeholder="field.placeholder || ''"
          />
        </el-form-item>
      </div>
    </el-form>

    <template #footer>
      <div class="drawer-form__footer">
        <el-button @click="closeDrawer">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">保存</el-button>
      </div>
    </template>
  </el-drawer>
</template>

<style scoped>
.drawer-form {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.drawer-form__section {
  padding: 18px;
  border-radius: 20px;
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
}

.drawer-form__section-title {
  margin-bottom: 14px;
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.drawer-form__switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
}

.drawer-form__footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  width: 100%;
}
</style>
