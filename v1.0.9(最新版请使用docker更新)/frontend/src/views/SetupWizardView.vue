<script setup lang="ts">
import axios, { type AxiosError } from 'axios'
import { ElMessage } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { initAdmin } from '@/api/setup'
import {
  createDriveAccount,
  fetchDriveAccounts,
  fetchDriveTypes,
  probeDriveAccount,
  setDriveAccountDefault,
  setDriveAccountStatus,
} from '@/api/extensions'
import { fetchResourceSearchSources, patchResourceSearchSource } from '@/api/resourceSearch'
import { fetchTMDBConfig, patchTMDBConfig } from '@/api/tmdb'
import DriveAccountDrawer from '@/components/extensions/DriveAccountDrawer.vue'
import NotificationConfigView from '@/views/extensions/NotificationConfigView.vue'
import { useAuthStore } from '@/stores/auth'
import { useSetupStore } from '@/stores/setup'
import type { DriveAccountItem, DriveTypeItem } from '@/types/extensions'
import type { ResourceSearchSourceItem, ResourceSearchSourceKey } from '@/types/resourceSearch'
import type { TMDBConfig } from '@/types/tmdb'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const setup = useSetupStore()

const activeStep = ref(0)
const backendReady = ref(true)
let statusRetryTimer: number | null = null

async function refreshSetupStatus() {
  if (statusRetryTimer) {
    window.clearTimeout(statusRetryTimer)
    statusRetryTimer = null
  }

  try {
    await setup.refreshStatus(true)
    backendReady.value = true
    if (setup.initialized && !auth.isAuthenticated) {
      router.replace('/login')
      return
    }
    if (!setup.initialized) {
      activeStep.value = 0
    }
  } catch {
    backendReady.value = false
    statusRetryTimer = window.setTimeout(refreshSetupStatus, 1500)
  }
}

const redirectTarget = computed(() => {
  const q = route.query.redirect
  if (!q) return '/'
  return typeof q === 'string' ? q : String(q[0] || '/')
})

const adminForm = reactive({
  username: 'admin',
  email: 'admin@example.com',
  password: '',
  confirmPassword: '',
})
const adminSubmitting = ref(false)

const canSubmitAdmin = computed(() => {
  if (!adminForm.username.trim()) return false
  if (!adminForm.email.trim()) return false
  if (!adminForm.password) return false
  if (adminForm.password !== adminForm.confirmPassword) return false
  return true
})

async function submitAdmin() {
  if (!canSubmitAdmin.value) return
  adminSubmitting.value = true
  try {
    const data = await initAdmin({
      username: adminForm.username.trim(),
      email: adminForm.email.trim(),
      password: adminForm.password,
    })
    await auth.afterLogin(data)
    setup.markInitialized()
    activeStep.value = 1
    ElMessage.success('管理员已创建并登录')
  } finally {
    adminSubmitting.value = false
  }
}

const driveTypes = ref<DriveTypeItem[]>([])
const driveAccounts = ref<DriveAccountItem[]>([])
const driveLoading = ref(false)
const driveDrawerVisible = ref(false)
const driveSubmitting = ref(false)

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
    query: { session_id: challenge.session_id, method: challenge.method, drive_type: challenge.drive_type },
  })
}

async function loadDriveData() {
  if (!auth.isAuthenticated) return
  driveLoading.value = true
  try {
    const [types, accounts] = await Promise.all([fetchDriveTypes(), fetchDriveAccounts()])
    driveTypes.value = types || []
    driveAccounts.value = accounts || []
  } finally {
    driveLoading.value = false
  }
}

async function handleCreateDrive(payload: {
  name: string
  drive_type: string
  config: Record<string, any>
  enabled: boolean
  is_default: boolean
  capacity_warning_threshold: number
}) {
  driveSubmitting.value = true
  try {
    const wantEnabled = Boolean(payload.enabled)
    const wantDefault = Boolean(payload.is_default)
    const created = await createDriveAccount({
      ...payload,
      enabled: false,
      is_default: false,
    })
    try {
      await probeDriveAccount(created.id)
    } catch (error) {
      const challenge = parseAuthChallenge(error)
      if (challenge) {
        driveDrawerVisible.value = false
        await loadDriveData()
        ElMessage.info('该账号需要二次认证，请继续完成验证')
        await gotoAuth(challenge)
        return
      }
      throw error
    }
    if (wantDefault) {
      await setDriveAccountDefault(created.id)
    }
    if (wantEnabled) {
      await setDriveAccountStatus(created.id, true)
    }
    ElMessage.success('网盘账号已添加')
    driveDrawerVisible.value = false
    await loadDriveData()
  } finally {
    driveSubmitting.value = false
  }
}

function nextStep() {
  activeStep.value = Math.min(activeStep.value + 1, 3)
}

function prevStep() {
  activeStep.value = Math.max(activeStep.value - 1, 0)
}

const sourcesLoading = ref(false)
const sourceSavingKey = ref<ResourceSearchSourceKey | null>(null)
const sources = reactive({
  net: { enabled: false },
  cloudsaver: { enabled: false, server: '', username: '', token: '' },
  pansou: { enabled: false, server: '' },
})

function applySources(list: ResourceSearchSourceItem[]) {
  const findSource = (key: ResourceSearchSourceKey) => list.find((item) => item.key === key) || null
  const net = findSource('net')
  sources.net.enabled = Boolean(net?.enabled)
  const cs = findSource('cloudsaver')
  sources.cloudsaver.enabled = Boolean(cs?.enabled)
  sources.cloudsaver.server = String(cs?.server || '')
  sources.cloudsaver.username = String(cs?.username || '')
  sources.cloudsaver.token = String(cs?.token || '')
  const ps = findSource('pansou')
  sources.pansou.enabled = Boolean(ps?.enabled)
  sources.pansou.server = String(ps?.server || '')
}

async function refreshSources() {
  if (!auth.isAuthenticated) return
  sourcesLoading.value = true
  try {
    const data = await fetchResourceSearchSources()
    applySources(data.sources || [])
  } finally {
    sourcesLoading.value = false
  }
}

async function saveSource(key: ResourceSearchSourceKey) {
  if (!auth.isAuthenticated) return
  sourceSavingKey.value = key
  try {
    if (key === 'net') {
      await patchResourceSearchSource('net', { enabled: Boolean(sources.net.enabled) })
      ElMessage.success('已保存')
      await refreshSources()
      return
    }
    if (key === 'pansou') {
      await patchResourceSearchSource('pansou', {
        enabled: Boolean(sources.pansou.enabled),
        server: sources.pansou.server ? String(sources.pansou.server).trim() : null,
      })
      ElMessage.success('已保存')
      await refreshSources()
      return
    }
    await patchResourceSearchSource('cloudsaver', {
      enabled: Boolean(sources.cloudsaver.enabled),
      server: sources.cloudsaver.server ? String(sources.cloudsaver.server).trim() : null,
      username: sources.cloudsaver.username ? String(sources.cloudsaver.username).trim() : null,
      token: sources.cloudsaver.token ? String(sources.cloudsaver.token).trim() : null,
    })
    ElMessage.success('已保存')
    await refreshSources()
  } finally {
    sourceSavingKey.value = null
  }
}

const tmdbLoading = ref(false)
const tmdbSaving = ref(false)
const tmdb = reactive({
  hasApiKey: false,
  apiKeyInput: '',
  language: 'zh-CN',
  posterLanguage: 'zh-CN',
  enableGuessitFallbackRename: true,
  tvRenameTemplate: '{title}.S{season}E{episode}{ext}',
  movieRenameTemplate: '{title_dot}.{year}{ext}',
})

function applyTMDBConfig(data: TMDBConfig) {
  tmdb.hasApiKey = Boolean(data.has_api_key)
  tmdb.language = String(data.language || 'zh-CN')
  tmdb.posterLanguage = String(data.poster_language || 'zh-CN')
  tmdb.enableGuessitFallbackRename = !Boolean(data.disable_guessit_tmdb_fallback_rename)
  tmdb.tvRenameTemplate = String(data.guessit_tmdb_tv_rename_template || '{title}.S{season}E{episode}{ext}')
  tmdb.movieRenameTemplate = String(data.guessit_tmdb_movie_rename_template || '{title_dot}.{year}{ext}')
}

async function refreshTMDB() {
  if (!auth.isAuthenticated) return
  tmdbLoading.value = true
  try {
    const data = await fetchTMDBConfig()
    applyTMDBConfig(data)
  } finally {
    tmdbLoading.value = false
  }
}

async function saveTMDB() {
  if (!auth.isAuthenticated) return
  tmdbSaving.value = true
  try {
    const payload: any = {
      language: tmdb.language ? String(tmdb.language).trim() : null,
      poster_language: tmdb.posterLanguage ? String(tmdb.posterLanguage).trim() : null,
      disable_guessit_tmdb_fallback_rename: !Boolean(tmdb.enableGuessitFallbackRename),
      guessit_tmdb_tv_rename_template: tmdb.tvRenameTemplate ? String(tmdb.tvRenameTemplate).trim() : null,
      guessit_tmdb_movie_rename_template: tmdb.movieRenameTemplate ? String(tmdb.movieRenameTemplate).trim() : null,
    }
    const apiKey = String(tmdb.apiKeyInput || '').trim()
    if (apiKey) payload.api_key = apiKey
    const data = await patchTMDBConfig(payload)
    tmdb.apiKeyInput = ''
    applyTMDBConfig(data)
    ElMessage.success('已保存')
  } finally {
    tmdbSaving.value = false
  }
}

function finish() {
  router.replace(redirectTarget.value || '/')
}

watch(
  () => activeStep.value,
  async (value) => {
    if (value >= 1) {
      await loadDriveData()
    }
    if (value >= 3) {
      await Promise.all([refreshSources(), refreshTMDB()])
    }
  },
  { immediate: true },
)

onMounted(async () => {
  await refreshSetupStatus()
})

onBeforeUnmount(() => {
  if (statusRetryTimer) {
    window.clearTimeout(statusRetryTimer)
    statusRetryTimer = null
  }
})
</script>

<template>
  <div class="setup">
    <el-card v-if="!backendReady" shadow="never" style="margin-bottom: 18px">
      <template #header>
        <div class="setup__card-title">后端启动中</div>
      </template>
      <div class="setup__sub">正在等待服务与数据库迁移完成，请稍后自动刷新或手动重试。</div>
      <div class="setup__actions" style="justify-content: flex-start">
        <el-button type="primary" @click="refreshSetupStatus">重试</el-button>
      </div>
    </el-card>

    <div class="setup__header">
      <div class="setup__title">初始化向导</div>
      <div class="setup__sub">首次运行需要创建管理员账号，随后可选配置网盘、通知与资源搜索。</div>
    </div>

    <el-steps :active="activeStep" finish-status="success" align-center style="margin-bottom: 22px">
      <el-step title="管理员" />
      <el-step title="网盘账号" />
      <el-step title="通知" />
      <el-step title="资源搜索 & TMDB" />
    </el-steps>

    <el-card v-show="activeStep === 0" shadow="never">
      <template #header>
        <div class="setup__card-title">1. 设置管理员账号</div>
      </template>
      <el-form label-position="top" class="setup__form">
        <el-form-item label="用户名">
          <el-input v-model="adminForm.username" autocomplete="username" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="adminForm.email" autocomplete="email" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="adminForm.password" type="password" show-password autocomplete="new-password" />
          <div class="setup__hint">至少 8 位且包含特殊字符</div>
        </el-form-item>
        <el-form-item label="确认密码">
          <el-input v-model="adminForm.confirmPassword" type="password" show-password autocomplete="new-password" />
        </el-form-item>
      </el-form>
      <div class="setup__actions">
        <el-button type="primary" :disabled="!canSubmitAdmin" :loading="adminSubmitting" @click="submitAdmin">创建并登录</el-button>
      </div>
    </el-card>

    <el-card v-show="activeStep === 1" shadow="never">
      <template #header>
        <div class="setup__card-title">2. 添加网盘账号（可跳过）</div>
      </template>
      <div class="setup__hint" style="margin-bottom: 12px">你可以先跳过，后续在“账号管理”页面再添加。</div>
      <div class="setup__actions" style="margin-bottom: 12px">
        <el-button type="primary" :disabled="driveTypes.length === 0" @click="driveDrawerVisible = true">新增账号</el-button>
        <el-button :loading="driveLoading" @click="loadDriveData">刷新</el-button>
      </div>
      <el-table :data="driveAccounts" :loading="driveLoading" style="width: 100%">
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column prop="drive_type" label="类型" width="140" />
        <el-table-column prop="runtime_status" label="状态" width="140" />
        <el-table-column prop="is_default" label="默认" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.is_default" type="success">默认</el-tag>
            <el-tag v-else type="info">否</el-tag>
          </template>
        </el-table-column>
      </el-table>
      <div class="setup__actions">
        <el-button @click="prevStep">上一步</el-button>
        <el-button @click="nextStep">跳过/下一步</el-button>
      </div>

      <DriveAccountDrawer v-model="driveDrawerVisible" :drive-types="driveTypes" :submitting="driveSubmitting" @save="handleCreateDrive" />
    </el-card>

    <el-card v-show="activeStep === 2" shadow="never">
      <template #header>
        <div class="setup__card-title">3. 通知配置（可跳过）</div>
      </template>
      <NotificationConfigView />
      <div class="setup__actions">
        <el-button @click="prevStep">上一步</el-button>
        <el-button @click="nextStep">跳过/下一步</el-button>
      </div>
    </el-card>

    <el-card v-show="activeStep === 3" shadow="never">
      <template #header>
        <div class="setup__card-title">4. 资源搜索 & TMDB（可跳过）</div>
      </template>

      <el-card class="setup__section" shadow="never">
        <template #header>
          <div class="setup__section-title">
            <div>资源搜索</div>
            <el-button text :loading="sourcesLoading" @click="refreshSources">刷新</el-button>
          </div>
        </template>

        <el-card class="setup__subsection" shadow="never">
          <template #header>
            <div class="setup__subsection-title">
              <div>网盘资源搜索（net）</div>
              <el-button size="small" type="primary" :loading="sourceSavingKey === 'net'" @click="saveSource('net')">保存</el-button>
            </div>
          </template>
          <el-switch v-model="sources.net.enabled" active-text="启用" inactive-text="禁用" />
        </el-card>

        <el-card class="setup__subsection" shadow="never">
          <template #header>
            <div class="setup__subsection-title">
              <div>CloudSaver（cloudsaver）</div>
              <el-button size="small" type="primary" :loading="sourceSavingKey === 'cloudsaver'" @click="saveSource('cloudsaver')">保存</el-button>
            </div>
          </template>
          <el-form label-position="top">
            <el-form-item>
              <el-switch v-model="sources.cloudsaver.enabled" active-text="启用" inactive-text="禁用" />
            </el-form-item>
            <el-form-item label="服务地址（可选）">
              <el-input v-model="sources.cloudsaver.server" placeholder="例如：https://xxx" />
            </el-form-item>
            <el-form-item label="用户名（可选）">
              <el-input v-model="sources.cloudsaver.username" />
            </el-form-item>
            <el-form-item label="Token（可选）">
              <el-input v-model="sources.cloudsaver.token" type="password" show-password />
            </el-form-item>
          </el-form>
        </el-card>

        <el-card class="setup__subsection" shadow="never">
          <template #header>
            <div class="setup__subsection-title">
              <div>Pansou（pansou）</div>
              <el-button size="small" type="primary" :loading="sourceSavingKey === 'pansou'" @click="saveSource('pansou')">保存</el-button>
            </div>
          </template>
          <el-form label-position="top">
            <el-form-item>
              <el-switch v-model="sources.pansou.enabled" active-text="启用" inactive-text="禁用" />
            </el-form-item>
            <el-form-item label="服务地址（可选）">
              <el-input v-model="sources.pansou.server" placeholder="例如：https://xxx" />
            </el-form-item>
          </el-form>
        </el-card>
      </el-card>

      <el-card class="setup__section" shadow="never">
        <template #header>
          <div class="setup__section-title">
            <div>TMDB</div>
            <el-button text :loading="tmdbLoading" @click="refreshTMDB">刷新</el-button>
          </div>
        </template>

        <el-form label-position="top">
          <el-form-item label="API Key">
            <el-input v-model="tmdb.apiKeyInput" type="password" show-password placeholder="留空表示不修改" />
            <div class="setup__hint">当前状态：{{ tmdb.hasApiKey ? '已配置' : '未配置' }}</div>
          </el-form-item>
          <el-form-item label="语言">
            <el-input v-model="tmdb.language" placeholder="例如：zh-CN" />
          </el-form-item>
          <el-form-item label="海报语言">
            <el-input v-model="tmdb.posterLanguage" placeholder="例如：zh-CN" />
          </el-form-item>
          <el-form-item>
            <el-switch v-model="tmdb.enableGuessitFallbackRename" active-text="启用 guessit+TMDB 兜底重命名" inactive-text="关闭兜底重命名" />
          </el-form-item>
          <el-form-item label="TV 重命名模板">
            <el-input v-model="tmdb.tvRenameTemplate" />
          </el-form-item>
          <el-form-item label="Movie 重命名模板">
            <el-input v-model="tmdb.movieRenameTemplate" />
          </el-form-item>
        </el-form>

        <div class="setup__actions" style="justify-content: flex-start">
          <el-button type="primary" :loading="tmdbSaving" @click="saveTMDB">保存 TMDB</el-button>
        </div>
      </el-card>

      <div class="setup__actions">
        <el-button @click="prevStep">上一步</el-button>
        <el-button @click="finish">完成</el-button>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.setup {
  padding: 20px;
  max-width: 980px;
  margin: 0 auto;
}

.setup__header {
  margin-bottom: 18px;
}

.setup__title {
  font-size: 20px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}

.setup__sub {
  margin-top: 6px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.setup__card-title {
  font-weight: 700;
}

.setup__form {
  margin-top: 8px;
}

.setup__actions {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.setup__hint {
  margin-top: 6px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.setup__section {
  margin-top: 14px;
  border-radius: 14px;
}

.setup__section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.setup__subsection {
  margin-top: 12px;
  border-radius: 14px;
}

.setup__subsection-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}
</style>
