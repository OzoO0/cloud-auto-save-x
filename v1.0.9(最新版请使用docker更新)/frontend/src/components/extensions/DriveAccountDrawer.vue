<script setup lang="ts">
import { useIsMobile } from '@/composables/useIsMobile'
import type { ConfigFieldItem, DriveAccountItem, DriveTypeItem } from '@/types/extensions'

type DriveAccountFormPayload = {
  name: string
  drive_type: string
  config: Record<string, any>
  enabled: boolean
  is_default: boolean
  capacity_warning_threshold: number
}

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    driveTypes: DriveTypeItem[]
    account?: DriveAccountItem | null
    submitting?: boolean
  }>(),
  {
    account: null,
    submitting: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  save: [payload: DriveAccountFormPayload]
}>()

const state = reactive({
  name: '',
  drive_type: '',
  configData: {} as Record<string, any>,
  enabled: true,
  is_default: false,
  capacity_warning_threshold: 85,
})

function cloneConfig<T>(value: T): T {
  return JSON.parse(JSON.stringify(value ?? {}))
}

const isEditing = computed(() => Boolean(props.account?.id))
const currentDriveType = computed(() => props.driveTypes.find((item) => item.code === state.drive_type) || null)
const currentDriveFields = computed<ConfigFieldItem[]>(() => currentDriveType.value?.config_fields || [])
const isMobile = useIsMobile()

function syncState() {
  if (props.account) {
    state.name = props.account.name
    state.drive_type = props.account.drive_type
    state.configData = cloneConfig(props.account.config || {})
    state.enabled = props.account.enabled
    state.is_default = props.account.is_default
    state.capacity_warning_threshold = props.account.capacity_warning_threshold || 85
    return
  }

  state.name = ''
  state.drive_type = props.driveTypes[0]?.code || ''
  state.configData = cloneConfig(props.driveTypes[0]?.default_config || {})
  state.enabled = true
  state.is_default = false
  state.capacity_warning_threshold = 85
}

watch(
  () => [props.modelValue, props.account, props.driveTypes] as const,
  ([visible]) => {
    if (!visible) return
    syncState()
  },
  { immediate: true, deep: true },
)

watch(
  () => state.drive_type,
  (value, oldValue) => {
    if (!value || value === oldValue || isEditing.value) return
    const target = props.driveTypes.find((item) => item.code === value)
    state.configData = cloneConfig(target?.default_config || {})
  },
)

function closeDrawer() {
  emit('update:modelValue', false)
}

function submit() {
  emit('save', {
    name: state.name.trim(),
    drive_type: state.drive_type,
    config: cloneConfig(state.configData),
    enabled: state.enabled,
    is_default: state.is_default,
    capacity_warning_threshold: state.capacity_warning_threshold,
  })
}
</script>

<template>
  <el-drawer
    :model-value="modelValue"
    :title="isEditing ? '编辑账号' : '新增账号'"
    :size="isMobile ? '100%' : '520px'"
    @close="closeDrawer"
  >
    <el-form label-position="top" class="drawer-form">
      <div class="drawer-form__section">
        <div class="drawer-form__section-title">基本信息</div>
        <el-form-item label="账号名称">
          <el-input v-model="state.name" placeholder="例如：夸克主账号" />
        </el-form-item>
        <el-form-item label="网盘类型">
          <el-select v-model="state.drive_type" style="width: 100%" :disabled="isEditing">
            <el-option v-for="item in driveTypes" :key="item.code" :label="item.drive_name" :value="item.code" />
          </el-select>
        </el-form-item>
      </div>

      <div class="drawer-form__section">
        <div class="drawer-form__section-title">状态与预警</div>
        <el-form-item label="容量预警阈值">
          <el-input-number v-model="state.capacity_warning_threshold" :min="1" :max="100" style="width: 100%" />
        </el-form-item>
        <div class="drawer-form__switch-row">
          <el-switch v-model="state.enabled" active-text="启用账号" inactive-text="禁用账号" />
          <el-switch v-model="state.is_default" active-text="设为默认账号" inactive-text="普通账号" />
        </div>
      </div>

      <div class="drawer-form__section">
        <div class="drawer-form__section-title">登录配置</div>
        <el-alert
          v-if="isEditing"
          title="当前显示的是已保存的结构化登录参数，保存后会直接覆盖当前账号配置。"
          type="info"
          :closable="false"
          style="margin-bottom: 16px"
        />
        <el-form-item v-for="field in currentDriveFields" :key="field.key" :label="field.label || field.key">
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
</style>
