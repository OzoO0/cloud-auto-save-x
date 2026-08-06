<script setup lang="ts">
import type { ConfigFieldItem, PluginItem } from '@/types/extensions'
import { useIsMobile } from '@/composables/useIsMobile'

type PluginPayload = {
  enabled: boolean
  priority: number
  config: Record<string, any>
}

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    plugin?: PluginItem | null
    submitting?: boolean
  }>(),
  {
    plugin: null,
    submitting: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  save: [payload: PluginPayload]
}>()

const state = reactive({
  enabled: false,
  priority: 100,
  configData: {} as Record<string, any>,
  configText: '{}',
})

const fields = computed<ConfigFieldItem[]>(() => props.plugin?.config_fields || [])
const taskFields = computed<ConfigFieldItem[]>(() => props.plugin?.task_config_fields || [])
const useStructuredForm = computed(() => fields.value.length > 0)
const isMobile = useIsMobile()

function cloneConfig<T>(value: T): T {
  return JSON.parse(JSON.stringify(value ?? {}))
}

watch(
  () => [props.modelValue, props.plugin] as const,
  ([visible]) => {
    if (!visible || !props.plugin) return
    state.enabled = props.plugin.enabled
    state.priority = props.plugin.priority
    state.configData = cloneConfig(props.plugin.config || {})
    state.configText = JSON.stringify(props.plugin.config || {}, null, 2)
  },
  { immediate: true, deep: true },
)

function closeDrawer() {
  emit('update:modelValue', false)
}

function submit() {
  emit('save', {
    enabled: state.enabled,
    priority: state.priority,
    config: useStructuredForm.value ? cloneConfig(state.configData) : JSON.parse(state.configText || '{}'),
  })
}
</script>

<template>
  <el-drawer
    :model-value="modelValue"
    :title="plugin ? `配置插件 · ${plugin.plugin_key}` : '配置插件'"
    :size="isMobile ? '100%' : '560px'"
    @close="closeDrawer"
  >
    <el-form v-if="plugin" label-position="top" class="drawer-form">
      <div class="drawer-form__section">
        <div class="drawer-form__section-title">运行控制</div>
        <div class="drawer-form__switch-row">
          <el-switch v-model="state.enabled" active-text="启用插件" inactive-text="禁用插件" />
          <el-form-item label="优先级" style="margin: 0">
            <el-input-number v-model="state.priority" :min="0" :max="9999" />
          </el-form-item>
        </div>
      </div>

      <div class="drawer-form__section">
        <div class="drawer-form__section-title">全局配置</div>
        <template v-if="useStructuredForm">
          <el-form-item v-for="field in fields" :key="field.key" :label="field.label || field.key">
            <el-switch
              v-if="field.input_type === 'switch'"
              v-model="state.configData[field.key]"
              active-text="开启"
              inactive-text="关闭"
            />
            <el-input-number
              v-else-if="field.input_type === 'number'"
              v-model="state.configData[field.key]"
              style="width: 100%"
            />
            <el-input
              v-else-if="field.input_type === 'textarea'"
              v-model="state.configData[field.key]"
              type="textarea"
              :rows="field.secret ? 4 : 3"
              :placeholder="field.placeholder || ''"
            />
            <el-input
              v-else
              v-model="state.configData[field.key]"
              :type="field.input_type === 'password' ? 'password' : 'text'"
              :placeholder="field.placeholder || ''"
              :show-password="field.input_type === 'password'"
            />
            <div v-if="field.description" class="drawer-form__hint">{{ field.description }}</div>
          </el-form-item>
        </template>
        <el-form-item v-else label="全局配置(JSON)">
          <el-input v-model="state.configText" type="textarea" :rows="12" />
        </el-form-item>
      </div>

      <div class="drawer-form__section">
        <div class="drawer-form__section-title">任务配置说明</div>
        <div v-if="taskFields.length" class="task-help-list">
          <div v-for="field in taskFields" :key="field.key" class="task-help-item">
            <strong>{{ field.label || field.key }}</strong>
            <span>{{ field.description || '未提供说明' }}</span>
          </div>
        </div>
        <el-empty v-else description="该插件暂无任务配置说明" :image-size="72" />
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

.drawer-form__hint {
  margin-top: 6px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.drawer-form__footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  width: 100%;
}

.task-help-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.task-help-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
  line-height: 1.5;
}
</style>
