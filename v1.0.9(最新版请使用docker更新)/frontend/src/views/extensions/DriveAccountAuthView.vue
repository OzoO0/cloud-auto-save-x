<script setup lang="ts">
import { ElMessage } from 'element-plus'
import type { AxiosError } from 'axios'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  fetchDriveAccountAuthSession,
  pollDriveAccountQrcodeAuth,
  sendDriveAccountSms,
  startDriveAccountAuth,
  startDriveAccountQrcodeAuth,
  submitDriveAccountCaptcha,
  submitDriveAccountSms,
} from '@/api/extensions'
import type { DriveAccountItem } from '@/types/extensions'

type AuthMethod = 'captcha' | 'sms' | 'qrcode'

type AuthChallenge = {
  account_id: number
  drive_type: string
  method: AuthMethod
  session_id: string
  payload?: Record<string, any>
}

type ApiErrorBody = {
  code?: string
  message?: string
  detail?: string
}

const route = useRoute()
const router = useRouter()

const accountId = computed(() => Number(route.params.accountId || 0))
const driveType = computed(() => String(route.query.drive_type || payload.value.drive_type || '').trim().toLowerCase())
const canStartQrcode = computed(() => driveType.value === 'aliyun')

const loading = ref(false)
const account = ref<DriveAccountItem | null>(null)
const method = ref<AuthMethod>('captcha')
const sessionId = ref('')
const payload = ref<Record<string, any>>({})

const captchaCode = ref('')
const smsCode = ref('')
const smsSending = ref(false)
const captchaSubmitting = ref(false)
const smsSubmitting = ref(false)
const qrcodePolling = ref(false)

let pollTimer: number | null = null

function stopPoll() {
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

function parseChallengeFromError(e: unknown): AuthChallenge | null {
  const err = e as AxiosError<ApiErrorBody>
  const detail = err?.response?.data?.detail
  if (!detail || typeof detail !== 'string') return null
  try {
    const parsed = JSON.parse(detail)
    if (!parsed?.session_id || !parsed?.method) return null
    return parsed as AuthChallenge
  } catch {
    return null
  }
}

async function startFlow() {
  stopPoll()
  loading.value = true
  try {
    sessionId.value = ''
    payload.value = {}
    try {
      const result = await startDriveAccountAuth(accountId.value)
      account.value = result
      ElMessage.success('账号已登录，无需二次认证')
      await router.replace('/extensions/drives')
    } catch (e) {
      const challenge = parseChallengeFromError(e)
      if (!challenge) throw e
      method.value = challenge.method
      sessionId.value = challenge.session_id
      payload.value = { ...(challenge.payload || {}), drive_type: challenge.drive_type }
      if (method.value === 'qrcode') startAutoPoll()
    }
  } finally {
    loading.value = false
  }
}

async function startQrcodeFlow() {
  stopPoll()
  loading.value = true
  try {
    const resp = await startDriveAccountQrcodeAuth(accountId.value)
    method.value = 'qrcode'
    sessionId.value = String(resp.session_id || '')
    payload.value = { ...(resp.payload || {}), drive_type: 'aliyun' }
    startAutoPoll()
  } finally {
    loading.value = false
  }
}

async function submitCaptcha() {
  if (!sessionId.value) return
  captchaSubmitting.value = true
  try {
    const res = await submitDriveAccountCaptcha(sessionId.value, captchaCode.value.trim())
    account.value = res
    ElMessage.success('验证码已验证，账号已登录')
    await router.replace('/extensions/drives')
  } catch (e) {
    const challenge = parseChallengeFromError(e)
    if (challenge) {
      method.value = challenge.method
      sessionId.value = challenge.session_id
      payload.value = { ...(challenge.payload || {}), drive_type: challenge.drive_type }
      captchaCode.value = ''
      if (method.value === 'qrcode') startAutoPoll()
      return
    }
    throw e
  } finally {
    captchaSubmitting.value = false
  }
}

async function handleSendSms() {
  if (!sessionId.value) return
  smsSending.value = true
  try {
    await sendDriveAccountSms(sessionId.value)
    ElMessage.success('短信验证码已发送')
  } finally {
    smsSending.value = false
  }
}

async function submitSms() {
  if (!sessionId.value) return
  smsSubmitting.value = true
  try {
    const res = await submitDriveAccountSms(sessionId.value, smsCode.value.trim())
    account.value = res
    ElMessage.success('短信已验证，账号已登录')
    await router.replace('/extensions/drives')
  } catch (e) {
    const challenge = parseChallengeFromError(e)
    if (challenge) {
      method.value = challenge.method
      sessionId.value = challenge.session_id
      payload.value = { ...(challenge.payload || {}), drive_type: challenge.drive_type }
      smsCode.value = ''
      if (method.value === 'qrcode') startAutoPoll()
      return
    }
    throw e
  } finally {
    smsSubmitting.value = false
  }
}

async function pollQrcodeOnce() {
  if (!sessionId.value) return
  qrcodePolling.value = true
  try {
    const res = await pollDriveAccountQrcodeAuth(sessionId.value)
    account.value = res
    ElMessage.success('扫码成功，账号已登录')
    stopPoll()
    await router.replace('/extensions/drives')
  } catch (e) {
    const challenge = parseChallengeFromError(e)
    if (challenge) {
      payload.value = { ...payload.value, ...(challenge.payload || {}), drive_type: challenge.drive_type }
      const status = String(payload.value.status || '')
      if (status === 'EXPIRED' || status === 'CANCELED') stopPoll()
      return
    }
    throw e
  } finally {
    qrcodePolling.value = false
  }
}

function startAutoPoll() {
  stopPoll()
  pollTimer = window.setInterval(() => {
    pollQrcodeOnce()
  }, 2000)
}

onMounted(() => {
  const qSession = String(route.query.session_id || '')
  const qMethod = String(route.query.method || '') as AuthMethod
  if (qSession && qMethod) {
    sessionId.value = qSession
    method.value = qMethod
    loading.value = true
    fetchDriveAccountAuthSession(qSession)
      .then((data) => {
        payload.value = { ...(data?.payload || {}), drive_type: data?.drive_type || route.query.drive_type || '' }
        if (method.value === 'qrcode') startAutoPoll()
      })
      .finally(() => {
        loading.value = false
      })
    return
  }
  startFlow()
})

onBeforeUnmount(stopPoll)
</script>

<template>
  <div class="shell-page" v-loading="loading">
    <div class="section-header">
      <div class="section-header__title">
        <h2>账号二次认证</h2>
      </div>
      <div class="toolbar__right">
        <el-button @click="router.replace('/extensions/drives')">返回列表</el-button>
        <el-button type="primary" @click="startFlow">重新检测</el-button>
        <el-button v-if="method !== 'qrcode' && canStartQrcode" @click="startQrcodeFlow">扫码登录</el-button>
      </div>
    </div>

    <section class="glass-panel auth-panel">
      <template v-if="method === 'captcha'">
        <el-alert type="info" show-icon :closable="false" title="该账号登录需要输入验证码。" style="margin-bottom: 16px" />
        <div class="auth-grid">
          <div class="auth-left">
            <img v-if="payload.image_base64" class="captcha-img" :src="`data:image/png;base64,${payload.image_base64}`" alt="captcha" />
            <div v-else class="auth-empty">未获取到验证码图片，可点击“重新检测”。</div>
          </div>
          <div class="auth-right">
            <el-input v-model="captchaCode" placeholder="输入验证码" />
            <div class="auth-actions">
              <el-button :loading="captchaSubmitting" type="primary" @click="submitCaptcha">提交验证码</el-button>
            </div>
          </div>
        </div>
      </template>

      <template v-else-if="method === 'sms'">
        <el-alert type="info" show-icon :closable="false" title="该账号登录需要短信验证。" style="margin-bottom: 16px" />
        <div class="auth-grid">
          <div class="auth-left">
            <div class="auth-meta">
              <div class="auth-meta__row">
                <span class="auth-meta__label">手机号</span>
                <span class="auth-meta__value">{{ payload.mobile || '-' }}</span>
              </div>
              <div class="auth-meta__row" v-if="payload.show_name">
                <span class="auth-meta__label">账号</span>
                <span class="auth-meta__value">{{ payload.show_name }}</span>
              </div>
            </div>
          </div>
          <div class="auth-right">
            <div class="auth-actions">
              <el-button :loading="smsSending" @click="handleSendSms">发送验证码</el-button>
            </div>
            <el-input v-model="smsCode" placeholder="输入短信验证码" style="margin-top: 12px" />
            <div class="auth-actions">
              <el-button :loading="smsSubmitting" type="primary" @click="submitSms">提交短信验证码</el-button>
            </div>
          </div>
        </div>
      </template>

      <template v-else>
        <el-alert type="info" show-icon :closable="false" title="请使用手机扫描二维码完成登录。" style="margin-bottom: 16px" />
        <div class="auth-grid">
          <div class="auth-left">
            <img v-if="payload.qrcode_url" class="qrcode-img" :src="payload.qrcode_url" alt="qrcode" />
            <div v-else class="auth-empty">未获取到二维码，可点击“扫码登录”。</div>
          </div>
          <div class="auth-right">
            <div class="auth-meta">
              <div class="auth-meta__row">
                <span class="auth-meta__label">状态</span>
                <span class="auth-meta__value">{{ payload.message || payload.status || '-' }}</span>
              </div>
            </div>
            <div class="auth-actions">
              <el-button :loading="qrcodePolling" type="primary" @click="pollQrcodeOnce">刷新状态</el-button>
            </div>
          </div>
        </div>
      </template>
    </section>
  </div>
</template>

<style scoped>
.auth-panel {
  padding: 18px;
}

.auth-grid {
  display: grid;
  grid-template-columns: 220px 1fr;
  gap: 16px;
}

.auth-left {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 220px;
  border: 1px dashed var(--el-border-color);
  border-radius: 16px;
  background: var(--el-fill-color-blank);
}

.auth-right {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 12px;
}

.captcha-img,
.qrcode-img {
  width: 200px;
  height: 200px;
  object-fit: contain;
}

.auth-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.auth-empty {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  padding: 12px;
  text-align: center;
}

.auth-meta {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
  padding: 12px;
}

.auth-meta__row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.auth-meta__label {
  color: var(--el-text-color-secondary);
}

.auth-meta__value {
  color: var(--el-text-color-primary);
  font-weight: 600;
}

@media (max-width: 720px) {
  .auth-grid {
    grid-template-columns: 1fr;
  }
  .auth-left {
    min-height: 180px;
  }
}
</style>
