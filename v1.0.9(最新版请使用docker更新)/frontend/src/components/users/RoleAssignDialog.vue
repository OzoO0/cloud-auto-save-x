<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type { RoleItem } from '@/types/user'

const props = defineProps<{
  modelValue: boolean
  roles: RoleItem[]
  selectedRoleIds: number[]
  title?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  submit: [value: number[]]
}>()

const innerVisible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const checkedRoleIds = ref<number[]>([])

watch(
  () => props.selectedRoleIds,
  (value) => {
    checkedRoleIds.value = [...value]
  },
  { immediate: true },
)

function handleSubmit() {
  emit('submit', checkedRoleIds.value)
}
</script>

<template>
  <el-dialog v-model="innerVisible" :title="title || '分配角色'" width="420px">
    <el-checkbox-group v-model="checkedRoleIds" class="dialog-role-list">
      <el-checkbox v-for="role in roles" :key="role.id" :value="role.id">
        {{ role.name }}
      </el-checkbox>
    </el-checkbox-group>
    <template #footer>
      <el-button @click="innerVisible = false">取消</el-button>
      <el-button type="primary" @click="handleSubmit">保存</el-button>
    </template>
  </el-dialog>
</template>
