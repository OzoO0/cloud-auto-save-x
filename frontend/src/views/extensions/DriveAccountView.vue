<script setup lang="ts">
import axios, { type AxiosError } from 'axios'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'

import CapacityAccountCard from '@/components/dashboard/CapacityAccountCard.vue'
import DriveAccountDrawer from '@/components/extensions/DriveAccountDrawer.vue'
import {
  createDriveAccount,
  deleteDriveAccount,
  fetchDriveAccounts,
  fetchDriveTypes,
  fetchDriveAccountProbeScheduler,
  patchDriveAccountProbeScheduler,
  probeDriveAccount,
  refreshDriveAccountProfiles,
  setDriveAccountDefault,
  setDriveAccountStatus,
  signInDriveAccount,
  updateDriveAccount,
} from '@/api/extensions'
import { DRIVE_ACCOUNT_WRITE } from '@/constants/permissions'
import { useAuthStore } from '@/stores/auth'
import { useIsMobile } from '@/composables/useIsMobile'
import type { ConfigFieldItem, DriveAccountItem, DriveTypeItem } from '@/types/extensions'
import { validateCrontab5, validateTimezone } from '@/utils/cron'

const auth = useAuthStore()
const canWrite = computed(() => auth.permissions.includes(DRIVE_ACCOUNT_WRITE))
const router = useRouter()

const loading = ref(false)
const submitting = ref(false)
const refreshing = ref(false)
const accounts = ref<DriveAccountItem[]>([])
const driveTypes = ref<DriveTypeItem[]>([])
const drawerVisible = ref(false)
const currentAccount = ref<DriveAccountItem | null>(null)
const isMobile = useIsMobile()

const deleteDialog = reactive({
  visible: false,
  deleting: false,
  row: null as DriveAccountItem | null,
})

const createdDialog = reactive({
  visible: false,
  accountId: 0,
  name: '',
  driveType: '',
  driveName: '',
  enabled: true,
  isDefault: false,
})

const probeScheduler = reactive({
  loading: false,
  saving: false,
  data: {
    enabled: true,
    crontab: '0 4 * * *',
    timezone: 'Asia/Shanghai',
    enabled_only: true,
  } as Record<string, any>,
})

const filters = reactive({
  keyword: '',
  drive_type: '',
  status: 'all',
  warnings_only: false,
})

type ApiErrorBody = {
  code?: string
  message?: string
  detail?: string
}

type AuthChallenge = {
  account_id: number
  drive_type: string
  method: string
  session_id: string
}

function parseAuthChallenge(error: unknown): AuthChallenge | null {
  if (!axios.isAxiosError(error)) return null
  const err = error as AxiosError<ApiErrorBody>
  if (err.response?.status !== 409) return null
  if (err.response?.data?.code !== 'DRIVE_ACCOUNT_AUTH_REQUIRED' && err.response?.data?.code !== 'DRIVE_ACCOUNT_AUTH_PENDING') return null
  const detail = err.response?.data?.detail
  if (!detail || typeof detail !== 'string') return null
  try {
    const parsed = JSON.parse(detail)
    if (!parsed?.session_id || !parsed?.method) return null
    return parsed as AuthChallenge
  } catch {
    return null
  }
}

async function gotoAuth(challenge: AuthChallenge) {
  await router.push({
    name: 'DriveAccountAuth',
    params: { accountId: String(challenge.account_id) },
    query: { session_id: challenge.session_id, method: challenge.method },
  })
}

function getDriveTypeMeta(code: string) {
  return driveTypes.value.find((item) => item.code === code) || null
}

function hasAnyConfigValue(configData: Record<string, any>, fields: ConfigFieldItem[]) {
  return fields.some((field) => {
    const value = configData[field.key]
    if (typeof value === 'boolean') return value
    if (typeof value === 'number') return !Number.isNaN(value)
    return String(value ?? '').trim() !== ''
  })
}

const filteredAccounts = computed(() =>
  accounts.value.filter((item) => {
    const matchesKeyword = !filters.keyword || [item.name, item.profile?.nickname, item.profile?.username].some((value) =>
      String(value || '')
        .toLowerCase()
        .includes(filters.keyword.toLowerCase()),
    )
    const matchesDrive = !filters.drive_type || item.drive_type === filters.drive_type
    const matchesStatus =
      filters.status === 'all' ||
      (filters.status === 'enabled' && item.enabled) ||
      (filters.status === 'disabled' && !item.enabled)
    const isWarning = (item.usage_ratio || 0) >= item.capacity_warning_threshold / 100
    const matchesWarning = !filters.warnings_only || isWarning
    return matchesKeyword && matchesDrive && matchesStatus && matchesWarning
  }),
)

const summary = computed(() => ({
  account_count: accounts.value.length,
  enabled_count: accounts.value.filter((item) => item.enabled).length,
  default_count: accounts.value.filter((item) => item.is_default).length,
  warning_count: accounts.value.filter((item) => (item.usage_ratio || 0) >= item.capacity_warning_threshold / 100).length,
}))

async function loadData() {
  loading.value = true
  try {
    const [accountData, driveTypeData] = await Promise.all([fetchDriveAccounts(), fetchDriveTypes()])
    accounts.value = accountData
    driveTypes.value = driveTypeData
  } finally {
    loading.value = false
  }
}

async function loadProbeScheduler() {
  probeScheduler.loading = true
  try {
    probeScheduler.data = await fetchDriveAccountProbeScheduler()
  } finally {
    probeScheduler.loading = false
  }
}

async function saveProbeScheduler() {
  if (!canWrite.value) return
  const cronCheck = validateCrontab5(String(probeScheduler.data.crontab || ''))
  if (!cronCheck.ok) {
    ElMessage.error(cronCheck.message)
    return
  }
  const tzCheck = validateTimezone(String(probeScheduler.data.timezone || ''))
  if (!tzCheck.ok) {
    ElMessage.error(tzCheck.message)
    return
  }
  probeScheduler.data.crontab = cronCheck.normalized || probeScheduler.data.crontab
  probeScheduler.data.timezone = tzCheck.normalized || probeScheduler.data.timezone
  probeScheduler.saving = true
  try {
    probeScheduler.data = await patchDriveAccountProbeScheduler({
      enabled: Boolean(probeScheduler.data.enabled),
      crontab: String(probeScheduler.data.crontab || '').trim(),
      timezone: String(probeScheduler.data.timezone || '').trim(),
      enabled_only: Boolean(probeScheduler.data.enabled_only),
    })
    ElMessage.success('已保存')
  } finally {
    probeScheduler.saving = false
  }
}

function openCreateDrawer() {
  currentAccount.value = null
  drawerVisible.value = true
}

function openEditDrawer(row: DriveAccountItem) {
  currentAccount.value = row
  drawerVisible.value = true
}

async function submitForm(payload: {
  name: string
  drive_type: string
  config: Record<string, any>
  enabled: boolean
  is_default: boolean
  capacity_warning_threshold: number
}) {
  const fields = getDriveTypeMeta(payload.drive_type)?.config_fields || []
  if (!currentAccount.value && !hasAnyConfigValue(payload.config, fields)) {
    ElMessage.warning('请填写当前网盘所需的登录参数')
    return
  }

  submitting.value = true
  try {
    if (currentAccount.value) {
      await updateDriveAccount(currentAccount.value.id, payload)
      ElMessage.success('账号已更新')
    } else {
      const created = await createDriveAccount(payload)
      try {
        await probeDriveAccount(created.id, { silentToast: true })
      } catch (e) {
        const challenge = parseAuthChallenge(e)
        if (challenge) {
          drawerVisible.value = false
          await loadData()
          ElMessage.info('该账号需要二次认证，请继续完成验证')
          await gotoAuth(challenge)
          return
        }
        throw e
      }
      const meta = getDriveTypeMeta(payload.drive_type)
      createdDialog.accountId = created.id
      createdDialog.name = payload.name
      createdDialog.driveType = payload.drive_type
      createdDialog.driveName = meta?.drive_name || payload.drive_type
      createdDialog.enabled = Boolean(payload.enabled)
      createdDialog.isDefault = Boolean(payload.is_default)
      createdDialog.visible = true
    }
    drawerVisible.value = false
    await loadData()
  } finally {
    submitting.value = false
  }
}

async function handleToggle(row: DriveAccountItem, enabled: boolean) {
  try {
    await setDriveAccountStatus(row.id, enabled)
    ElMessage.success('状态已更新')
  } catch (e) {
    const challenge = parseAuthChallenge(e)
    if (challenge) {
      ElMessage.info('该账号需要二次认证，请继续完成验证')
      await gotoAuth(challenge)
      return
    }
    throw e
  } finally {
    await loadData()
  }
}

async function handleSetDefault(row: DriveAccountItem) {
  await setDriveAccountDefault(row.id)
  ElMessage.success('默认账号已更新')
  await loadData()
}

async function handleProbe(row: DriveAccountItem) {
  try {
    await probeDriveAccount(row.id, { silentToast: true })
    ElMessage.success('账号已探测并刷新快照')
    await loadData()
  } catch (e) {
    const challenge = parseAuthChallenge(e)
    if (challenge) {
      ElMessage.info('该账号需要二次认证，请继续完成验证')
      await gotoAuth(challenge)
      return
    }
    throw e
  }
}

async function handleSignIn(row: DriveAccountItem) {
  const result = await signInDriveAccount(row.id)
  const message = result?.message ?? ''
  if (message) {
    ElMessage.success(String(message))
  } else {
    ElMessage.success('签到成功')
  }
}

function openDeleteDialog(row: DriveAccountItem) {
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
    await deleteDriveAccount(row.id)
    ElMessage.success('账号已删除')
    closeDeleteDialog()
    await loadData()
  } finally {
    deleteDialog.deleting = false
  }
}

async function handleRefreshProfiles() {
  refreshing.value = true
  try {
    await refreshDriveAccountProfiles()
    ElMessage.success('全部账号容量快照已刷新')
    await loadData()
  } finally {
    refreshing.value = false
  }
}

onMounted(loadData)
onMounted(loadProbeScheduler)
</script>

<template>
  <div class="shell-page" v-loading="loading">
    <div class="section-header">
      <div class="section-header__title">
        <h2>账号管理</h2>
      </div>
      <div class="toolbar__right">
        <el-button :loading="refreshing" @click="handleRefreshProfiles">刷新全部容量</el-button>
        <el-button type="primary" @click="loadData">刷新列表</el-button>
        <el-button v-if="canWrite" type="success" @click="openCreateDrawer">新增账号</el-button>
      </div>
    </div>

    <section class="metric-strip">
      <div class="glass-panel metric-tile">
        <div class="metric-tile__label">账号总数</div>
        <div class="metric-tile__value">{{ summary.account_count }}</div>
        <div class="metric-tile__hint">所有已接入的网盘账户</div>
      </div>
      <div class="glass-panel metric-tile">
        <div class="metric-tile__label">启用账号</div>
        <div class="metric-tile__value">{{ summary.enabled_count }}</div>
        <div class="metric-tile__hint">当前参与运行的账户</div>
      </div>
      <div class="glass-panel metric-tile">
        <div class="metric-tile__label">默认账号</div>
        <div class="metric-tile__value">{{ summary.default_count }}</div>
        <div class="metric-tile__hint">默认保存与执行入口</div>
      </div>
      <div class="glass-panel metric-tile">
        <div class="metric-tile__label">预警账号</div>
        <div class="metric-tile__value">{{ summary.warning_count }}</div>
        <div class="metric-tile__hint">已超过自定义容量阈值</div>
      </div>
    </section>

    <section class="glass-panel filter-strip">
      <div class="toolbar">
        <div class="toolbar__left">
          <el-input v-model="filters.keyword" clearable placeholder="搜索账号名 / 昵称" :style="{ width: isMobile ? '100%' : '240px' }" />
          <el-select v-model="filters.drive_type" clearable placeholder="网盘类型" :style="{ width: isMobile ? '100%' : '180px' }">
            <el-option v-for="item in driveTypes" :key="item.code" :label="item.drive_name" :value="item.code" />
          </el-select>
          <el-segmented
            v-model="filters.status"
            :options="[
              { label: '全部', value: 'all' },
              { label: '启用', value: 'enabled' },
              { label: '禁用', value: 'disabled' },
            ]"
          />
        </div>
        <div class="toolbar__right">
          <el-switch v-model="filters.warnings_only" active-text="仅看预警" inactive-text="全部账号" />
        </div>
      </div>
    </section>

    <section class="glass-panel dashboard-section" style="margin-bottom: 18px">
      <div class="dashboard-section__title">自动探测/签到</div>
      <div class="toolbar">
        <div class="toolbar__left">
          <el-switch v-model="probeScheduler.data.enabled" active-text="启用调度" inactive-text="暂停调度" />
          <el-input v-model="probeScheduler.data.crontab" placeholder="0 4 * * *" :style="{ width: isMobile ? '100%' : '220px' }" />
          <el-input v-model="probeScheduler.data.timezone" placeholder="Asia/Shanghai" :style="{ width: isMobile ? '100%' : '180px' }" />
          <el-switch v-model="probeScheduler.data.enabled_only" active-text="仅启用账号" inactive-text="全部账号" />
        </div>
        <div class="toolbar__right">
          <el-button :loading="probeScheduler.loading" @click="loadProbeScheduler">刷新</el-button>
          <el-button type="primary" :loading="probeScheduler.saving" :disabled="!canWrite" @click="saveProbeScheduler">保存</el-button>
        </div>
      </div>
    </section>

    <section v-if="filteredAccounts.length" class="card-grid">
      <CapacityAccountCard v-for="item in filteredAccounts" :key="item.id" :account="item">
        <template #actions>
          <el-button v-if="canWrite" text bg @click="openEditDrawer(item)">编辑</el-button>
          <el-button v-if="canWrite" text bg @click="handleToggle(item, !item.enabled)">
            {{ item.enabled ? '禁用' : '启用' }}
          </el-button>
          <el-button v-if="canWrite && !item.is_default" text bg @click="handleSetDefault(item)">设为默认</el-button>
          <el-button text bg @click="handleProbe(item)">探测</el-button>
          <el-button text bg @click="handleSignIn(item)">签到</el-button>
          <el-button v-if="canWrite" text bg type="danger" @click="openDeleteDialog(item)">删除</el-button>
        </template>
      </CapacityAccountCard>
    </section>

    <section v-else class="glass-panel dashboard-section">
      <div class="empty-copy">当前筛选条件下没有账号，试试清空筛选，或新增一个网盘账号开始管理。</div>
    </section>

    <DriveAccountDrawer
      v-model="drawerVisible"
      :account="currentAccount"
      :drive-types="driveTypes"
      :submitting="submitting"
      @save="submitForm"
    />

    <el-dialog
      v-model="deleteDialog.visible"
      title="删除账号"
      width="560px"
      :close-on-click-modal="false"
      @close="closeDeleteDialog"
    >
      <div v-if="deleteDialog.row" class="del">
        <el-alert type="warning" show-icon :closable="false" class="del__alert">
          <template #title>删除后不可恢复</template>
          <template #default>
            <div class="del__text">该账号的配置、容量快照与相关状态信息将被永久移除。</div>
          </template>
        </el-alert>

        <el-descriptions :column="1" border>
          <el-descriptions-item label="账号名">{{ deleteDialog.row.name }}</el-descriptions-item>
          <el-descriptions-item label="网盘类型">
            <el-tag>{{ getDriveTypeMeta(deleteDialog.row.drive_type)?.drive_name || deleteDialog.row.drive_type }}</el-tag>
            <span class="del__sub">{{ deleteDialog.row.drive_type }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="deleteDialog.row.enabled ? 'success' : 'info'">{{ deleteDialog.row.enabled ? '启用' : '禁用' }}</el-tag>
            <el-tag v-if="deleteDialog.row.is_default" type="warning" class="del__tag">默认</el-tag>
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

    <el-dialog
      v-model="createdDialog.visible"
      width="520px"
      :show-close="false"
      :close-on-click-modal="false"
    >
      <el-result icon="success" title="账号创建成功" sub-title="已自动发起探测，稍后可在卡片上看到容量与状态更新。">
        <template #extra>
          <div class="created__meta">
            <el-descriptions :column="1" border>
              <el-descriptions-item label="账号名">{{ createdDialog.name }}</el-descriptions-item>
              <el-descriptions-item label="网盘类型">
                <el-tag>{{ createdDialog.driveName }}</el-tag>
                <span class="created__sub">{{ createdDialog.driveType }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="状态">
                <el-tag :type="createdDialog.enabled ? 'success' : 'info'">{{ createdDialog.enabled ? '启用' : '禁用' }}</el-tag>
                <el-tag v-if="createdDialog.isDefault" type="warning" class="created__tag">默认</el-tag>
              </el-descriptions-item>
            </el-descriptions>
          </div>
          <div class="created__actions">
            <el-button @click="createdDialog.visible = false">关闭</el-button>
            <el-button type="primary" @click="createdDialog.visible = false">继续添加</el-button>
          </div>
        </template>
      </el-result>
    </el-dialog>
  </div>
</template>

<style scoped>
.del__alert {
  margin-bottom: 12px;
}
.del__text {
  color: var(--el-text-color-regular);
}
.del__sub {
  margin-left: 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.del__tag {
  margin-left: 8px;
}
.created__meta {
  width: 100%;
  margin-top: 12px;
}
.created__sub {
  margin-left: 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.created__tag {
  margin-left: 8px;
}
.created__actions {
  margin-top: 14px;
  display: flex;
  gap: 10px;
  justify-content: center;
}
</style>
