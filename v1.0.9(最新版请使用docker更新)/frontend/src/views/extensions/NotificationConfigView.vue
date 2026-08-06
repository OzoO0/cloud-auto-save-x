<script setup lang="ts">
import { ElMessage } from 'element-plus'

import { fetchNotificationConfig, sendNotificationTest, updateNotificationConfig } from '@/api/notifications'
import NotificationChannelCard, { type NotifyChannel } from '@/components/extensions/NotificationChannelCard.vue'
import NotificationChannelDrawer from '@/components/extensions/NotificationChannelDrawer.vue'
import { NOTIFY_WRITE } from '@/constants/permissions'
import { useAuthStore } from '@/stores/auth'
import { useIsMobile } from '@/composables/useIsMobile'
import type { NotificationChannelResult } from '@/types/notifications'

const auth = useAuthStore()
const canWrite = computed(() => auth.permissions.includes(NOTIFY_WRITE))

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const isMobile = useIsMobile()

const updatedAt = ref<string | null>(null)
const defaultConfig = ref<Record<string, any>>({})
const configData = ref<Record<string, any>>({})

const testDialogVisible = ref(false)
const testTitle = ref('测试通知')
const testContent = ref('这是一条测试消息。')
const testResults = ref<NotificationChannelResult[]>([])
const lastTests = ref<Record<string, { ok: boolean; error?: string | null }>>({})

const channelDrawerVisible = ref(false)
const currentChannel = ref<NotifyChannel | null>(null)
const channelSubmitting = ref(false)

const globalDrawerVisible = ref(false)
const globalJsonText = ref('{}')
const globalSubmitting = ref(false)

function hasValue(value: any) {
  if (typeof value === 'boolean') return value
  if (typeof value === 'number') return !Number.isNaN(value) && value !== 0
  return String(value ?? '').trim() !== ''
}

function toBool(value: any) {
  if (value === true) return true
  if (value === false) return false
  const text = String(value ?? '').trim().toLowerCase()
  return text === 'true' || text === '1' || text === 'yes' || text === 'on'
}

function normalizeConfig(payload: Record<string, any>) {
  const data = { ...payload }
  data.HITOKOTO = toBool(data.HITOKOTO)
  if ('SMTP_SSL' in data) {
    data.SMTP_SSL = toBool(data.SMTP_SSL)
  }
  return data
}

function channelEnabled(channelId: string) {
  const map = (configData.value || {}).__channel_enabled
  if (!map || typeof map !== 'object' || Array.isArray(map)) return false
  return map[channelId] === true
}

function setChannelEnabled(channelId: string, value: boolean) {
  if (!configData.value.__channel_enabled || typeof configData.value.__channel_enabled !== 'object' || Array.isArray(configData.value.__channel_enabled)) {
    configData.value.__channel_enabled = {}
  }
  configData.value.__channel_enabled[channelId] = value
}

function ensureDefaultChannelEnabledMap(list: NotifyChannel[]) {
  const existing = (configData.value || {}).__channel_enabled
  if (existing && typeof existing === 'object' && !Array.isArray(existing)) {
    return
  }
  const payload: Record<string, boolean> = {}
  for (const channel of list) {
    payload[channel.id] = false
  }
  configData.value.__channel_enabled = payload
}

const channels = computed<NotifyChannel[]>(() => [
  {
    id: 'bark',
    title: 'Bark',
    required_keys: ['BARK_PUSH'],
    summary_keys: ['BARK_PUSH', 'BARK_GROUP', 'BARK_SOUND'],
    fields: [
      { key: 'BARK_PUSH', label: 'BARK_PUSH', placeholder: 'https://api.day.app/xxx 或 设备码' },
      { key: 'BARK_ARCHIVE', label: 'BARK_ARCHIVE' },
      { key: 'BARK_GROUP', label: 'BARK_GROUP' },
      { key: 'BARK_SOUND', label: 'BARK_SOUND' },
      { key: 'BARK_ICON', label: 'BARK_ICON' },
      { key: 'BARK_LEVEL', label: 'BARK_LEVEL' },
      { key: 'BARK_URL', label: 'BARK_URL' },
    ],
  },
  {
    id: 'dingding',
    title: '钉钉机器人',
    required_keys: ['DD_BOT_TOKEN', 'DD_BOT_SECRET'],
    summary_keys: ['DD_BOT_TOKEN'],
    fields: [
      { key: 'DD_BOT_TOKEN', label: 'DD_BOT_TOKEN', input: 'password' },
      { key: 'DD_BOT_SECRET', label: 'DD_BOT_SECRET', input: 'password' },
    ],
  },
  {
    id: 'feishu',
    title: '飞书机器人',
    required_keys: ['FSKEY'],
    summary_keys: ['FSKEY'],
    fields: [{ key: 'FSKEY', label: 'FSKEY', input: 'password' }],
  },
  {
    id: 'gocqhttp',
    title: 'go-cqhttp',
    required_keys: ['GOBOT_URL', 'GOBOT_QQ'],
    summary_keys: ['GOBOT_URL', 'GOBOT_QQ'],
    fields: [
      { key: 'GOBOT_URL', label: 'GOBOT_URL', placeholder: 'http://127.0.0.1/send_private_msg 或 /send_group_msg' },
      { key: 'GOBOT_QQ', label: 'GOBOT_QQ', placeholder: 'user_id 或 group_id' },
      { key: 'GOBOT_TOKEN', label: 'GOBOT_TOKEN', input: 'password', placeholder: 'access_token（可选）' },
    ],
  },
  {
    id: 'gotify',
    title: 'Gotify',
    required_keys: ['GOTIFY_URL', 'GOTIFY_TOKEN'],
    summary_keys: ['GOTIFY_URL', 'GOTIFY_PRIORITY'],
    fields: [
      { key: 'GOTIFY_URL', label: 'GOTIFY_URL', placeholder: 'https://push.example.de:8080' },
      { key: 'GOTIFY_TOKEN', label: 'GOTIFY_TOKEN', input: 'password' },
      { key: 'GOTIFY_PRIORITY', label: 'GOTIFY_PRIORITY', input: 'number' },
    ],
  },
  {
    id: 'igot',
    title: 'iGot',
    required_keys: ['IGOT_PUSH_KEY'],
    summary_keys: ['IGOT_PUSH_KEY'],
    fields: [{ key: 'IGOT_PUSH_KEY', label: 'IGOT_PUSH_KEY', input: 'password' }],
  },
  {
    id: 'serverj',
    title: 'Server酱',
    required_keys: ['PUSH_KEY'],
    summary_keys: ['PUSH_KEY'],
    fields: [{ key: 'PUSH_KEY', label: 'PUSH_KEY', input: 'password' }],
  },
  {
    id: 'pushdeer',
    title: 'PushDeer',
    required_keys: ['DEER_KEY'],
    summary_keys: ['DEER_KEY', 'DEER_URL'],
    fields: [
      { key: 'DEER_KEY', label: 'DEER_KEY', input: 'password' },
      { key: 'DEER_URL', label: 'DEER_URL', placeholder: '默认 https://api2.pushdeer.com/message/push' },
    ],
  },
  {
    id: 'synology_chat',
    title: 'Synology Chat',
    required_keys: ['CHAT_URL', 'CHAT_TOKEN'],
    summary_keys: ['CHAT_URL'],
    fields: [
      { key: 'CHAT_URL', label: 'CHAT_URL' },
      { key: 'CHAT_TOKEN', label: 'CHAT_TOKEN', input: 'password' },
    ],
  },
  {
    id: 'pushplus',
    title: 'PushPlus',
    required_keys: ['PUSH_PLUS_TOKEN'],
    summary_keys: ['PUSH_PLUS_CHANNEL', 'PUSH_PLUS_TEMPLATE'],
    fields: [
      { key: 'PUSH_PLUS_TOKEN', label: 'PUSH_PLUS_TOKEN', input: 'password' },
      { key: 'PUSH_PLUS_USER', label: 'PUSH_PLUS_USER', placeholder: '群组编码（可选）' },
      { key: 'PUSH_PLUS_TEMPLATE', label: 'PUSH_PLUS_TEMPLATE', placeholder: 'html/txt/json/markdown/...' },
      { key: 'PUSH_PLUS_CHANNEL', label: 'PUSH_PLUS_CHANNEL', placeholder: 'wechat/webhook/cp/mail/...' },
      { key: 'PUSH_PLUS_WEBHOOK', label: 'PUSH_PLUS_WEBHOOK' },
      { key: 'PUSH_PLUS_CALLBACKURL', label: 'PUSH_PLUS_CALLBACKURL' },
      { key: 'PUSH_PLUS_TO', label: 'PUSH_PLUS_TO', placeholder: '好友令牌或企业微信用户ID（可选）' },
    ],
  },
  {
    id: 'weplus',
    title: '微加机器人',
    required_keys: ['WE_PLUS_BOT_TOKEN'],
    summary_keys: ['WE_PLUS_BOT_RECEIVER', 'WE_PLUS_BOT_VERSION'],
    fields: [
      { key: 'WE_PLUS_BOT_TOKEN', label: 'WE_PLUS_BOT_TOKEN', input: 'password' },
      { key: 'WE_PLUS_BOT_RECEIVER', label: 'WE_PLUS_BOT_RECEIVER' },
      { key: 'WE_PLUS_BOT_VERSION', label: 'WE_PLUS_BOT_VERSION', placeholder: 'pro/...' },
    ],
  },
  {
    id: 'qmsg',
    title: 'Qmsg 酱',
    required_keys: ['QMSG_KEY', 'QMSG_TYPE'],
    summary_keys: ['QMSG_TYPE'],
    fields: [
      { key: 'QMSG_TYPE', label: 'QMSG_TYPE', placeholder: 'send/...' },
      { key: 'QMSG_KEY', label: 'QMSG_KEY', input: 'password' },
    ],
  },
  {
    id: 'wecom_app',
    title: '企业微信应用消息',
    required_keys: ['QYWX_AM'],
    summary_keys: ['QYWX_AM', 'QYWX_ORIGIN'],
    fields: [
      { key: 'QYWX_ORIGIN', label: 'QYWX_ORIGIN', placeholder: '默认 https://qyapi.weixin.qq.com' },
      { key: 'QYWX_AM', label: 'QYWX_AM', placeholder: 'corpid,corpsecret,agentid,touser' },
    ],
  },
  {
    id: 'wecom_bot',
    title: '企业微信机器人',
    required_keys: ['QYWX_KEY'],
    summary_keys: ['QYWX_KEY'],
    fields: [{ key: 'QYWX_KEY', label: 'QYWX_KEY', input: 'password' }],
  },
  {
    id: 'telegram',
    title: 'Telegram',
    required_keys: ['TG_BOT_TOKEN', 'TG_USER_ID'],
    summary_keys: ['TG_USER_ID', 'TG_API_HOST'],
    fields: [
      { key: 'TG_BOT_TOKEN', label: 'TG_BOT_TOKEN', input: 'password' },
      { key: 'TG_USER_ID', label: 'TG_USER_ID' },
      { key: 'TG_API_HOST', label: 'TG_API_HOST', placeholder: '默认 https://api.telegram.org' },
      { key: 'TG_PROXY_HOST', label: 'TG_PROXY_HOST', placeholder: '代理 host（可选）' },
      { key: 'TG_PROXY_PORT', label: 'TG_PROXY_PORT', placeholder: '代理 port（可选）' },
      { key: 'TG_PROXY_AUTH', label: 'TG_PROXY_AUTH', placeholder: 'user:pass（可选）' },
    ],
  },
  {
    id: 'aibotk',
    title: '智能微秘书',
    required_keys: ['AIBOTK_KEY', 'AIBOTK_TYPE', 'AIBOTK_NAME'],
    summary_keys: ['AIBOTK_TYPE', 'AIBOTK_NAME'],
    fields: [
      { key: 'AIBOTK_KEY', label: 'AIBOTK_KEY', input: 'password' },
      { key: 'AIBOTK_TYPE', label: 'AIBOTK_TYPE', placeholder: 'room/contact' },
      { key: 'AIBOTK_NAME', label: 'AIBOTK_NAME', placeholder: '群名或好友昵称' },
    ],
  },
  {
    id: 'smtp',
    title: 'SMTP 邮件',
    required_keys: ['SMTP_SERVER', 'SMTP_SSL', 'SMTP_EMAIL', 'SMTP_PASSWORD', 'SMTP_NAME'],
    summary_keys: ['SMTP_SERVER', 'SMTP_EMAIL'],
    fields: [
      { key: 'SMTP_SERVER', label: 'SMTP_SERVER', placeholder: 'smtp.example.com:465' },
      { key: 'SMTP_SSL', label: 'SMTP_SSL', input: 'switch' },
      { key: 'SMTP_EMAIL', label: 'SMTP_EMAIL' },
      { key: 'SMTP_PASSWORD', label: 'SMTP_PASSWORD', input: 'password' },
      { key: 'SMTP_NAME', label: 'SMTP_NAME' },
      { key: 'SMTP_EMAIL_TO', label: 'SMTP_EMAIL_TO', placeholder: '多个用逗号分隔（可选）' },
      { key: 'SMTP_NAME_TO', label: 'SMTP_NAME_TO', placeholder: '多个用逗号分隔（可选）' },
    ],
  },
  {
    id: 'pushme',
    title: 'PushMe',
    required_keys: ['PUSHME_KEY'],
    summary_keys: ['PUSHME_URL'],
    fields: [
      { key: 'PUSHME_KEY', label: 'PUSHME_KEY', input: 'password' },
      { key: 'PUSHME_URL', label: 'PUSHME_URL' },
    ],
  },
  {
    id: 'chronocat',
    title: 'Chronocat',
    required_keys: ['CHRONOCAT_URL', 'CHRONOCAT_QQ', 'CHRONOCAT_TOKEN'],
    summary_keys: ['CHRONOCAT_URL', 'CHRONOCAT_QQ'],
    fields: [
      { key: 'CHRONOCAT_URL', label: 'CHRONOCAT_URL' },
      { key: 'CHRONOCAT_QQ', label: 'CHRONOCAT_QQ' },
      { key: 'CHRONOCAT_TOKEN', label: 'CHRONOCAT_TOKEN', input: 'password' },
    ],
  },
  {
    id: 'dodo',
    title: 'DoDo 机器人',
    required_keys: ['DODO_BOTTOKEN', 'DODO_BOTID', 'DODO_LANDSOURCEID', 'DODO_SOURCEID'],
    summary_keys: ['DODO_BOTID', 'DODO_SOURCEID'],
    fields: [
      { key: 'DODO_BOTTOKEN', label: 'DODO_BOTTOKEN', input: 'password' },
      { key: 'DODO_BOTID', label: 'DODO_BOTID' },
      { key: 'DODO_LANDSOURCEID', label: 'DODO_LANDSOURCEID' },
      { key: 'DODO_SOURCEID', label: 'DODO_SOURCEID' },
    ],
  },
  {
    id: 'webhook',
    title: '自定义 Webhook',
    required_keys: ['WEBHOOK_URL', 'WEBHOOK_METHOD'],
    summary_keys: ['WEBHOOK_METHOD', 'WEBHOOK_URL'],
    fields: [
      { key: 'WEBHOOK_URL', label: 'WEBHOOK_URL', placeholder: '必须包含 $title（可选 $content）' },
      { key: 'WEBHOOK_METHOD', label: 'WEBHOOK_METHOD', placeholder: 'POST / GET ...' },
      { key: 'WEBHOOK_HEADERS', label: 'WEBHOOK_HEADERS', input: 'textarea', rows: 3, placeholder: 'JSON 字符串' },
      { key: 'WEBHOOK_BODY', label: 'WEBHOOK_BODY', input: 'textarea', rows: 4, placeholder: '支持 $title / $content 替换' },
      { key: 'WEBHOOK_CONTENT_TYPE', label: 'WEBHOOK_CONTENT_TYPE', placeholder: 'application/json' },
    ],
  },
  {
    id: 'ntfy',
    title: 'Ntfy',
    required_keys: ['NTFY_TOPIC'],
    summary_keys: ['NTFY_URL', 'NTFY_TOPIC'],
    fields: [
      { key: 'NTFY_URL', label: 'NTFY_URL', placeholder: '默认 https://ntfy.sh' },
      { key: 'NTFY_TOPIC', label: 'NTFY_TOPIC' },
      { key: 'NTFY_PRIORITY', label: 'NTFY_PRIORITY' },
      { key: 'NTFY_TOKEN', label: 'NTFY_TOKEN', input: 'password' },
      { key: 'NTFY_USERNAME', label: 'NTFY_USERNAME' },
      { key: 'NTFY_PASSWORD', label: 'NTFY_PASSWORD', input: 'password' },
      { key: 'NTFY_ACTIONS', label: 'NTFY_ACTIONS', input: 'textarea', rows: 3, placeholder: 'actions（可选）' },
    ],
  },
  {
    id: 'wxpusher',
    title: 'WxPusher',
    required_keys: ['WXPUSHER_APP_TOKEN'],
    summary_keys: ['WXPUSHER_TOPIC_IDS', 'WXPUSHER_UIDS'],
    fields: [
      { key: 'WXPUSHER_APP_TOKEN', label: 'WXPUSHER_APP_TOKEN', input: 'password' },
      { key: 'WXPUSHER_TOPIC_IDS', label: 'WXPUSHER_TOPIC_IDS', placeholder: '多个用英文分号 ; 分隔' },
      { key: 'WXPUSHER_UIDS', label: 'WXPUSHER_UIDS', placeholder: '多个用英文分号 ; 分隔' },
    ],
  },
])

function channelConfiguredOverride(channel: NotifyChannel) {
  if (channel.id === 'wxpusher') {
    const token = String(configData.value.WXPUSHER_APP_TOKEN ?? '').trim()
    const topicIds = String(configData.value.WXPUSHER_TOPIC_IDS ?? '').trim()
    const uids = String(configData.value.WXPUSHER_UIDS ?? '').trim()
    return Boolean(token) && (Boolean(topicIds) || Boolean(uids))
  }
  return undefined
}

const summary = computed(() => {
  const items = channels.value
  const configuredCount = items.filter((c) => channelConfiguredOverride(c) ?? c.required_keys.every((k) => hasValue(configData.value[k]))).length
  const enabledCount = items.filter((c) => channelEnabled(c.id)).length
  const lastFailed = Object.values(lastTests.value).filter((item) => item && item.ok === false).length
  return { total: items.length, configured: configuredCount, enabled: enabledCount, last_failed: lastFailed }
})

async function loadData() {
  loading.value = true
  try {
    const res = await fetchNotificationConfig()
    updatedAt.value = res.updated_at || null
    defaultConfig.value = res.default_config || {}
    configData.value = normalizeConfig({ ...(res.default_config || {}), ...(res.config || {}) })
    globalJsonText.value = JSON.stringify(configData.value, null, 2)
    ensureDefaultChannelEnabledMap(channels.value)
  } finally {
    loading.value = false
  }
}

async function saveAll() {
  if (!canWrite.value) {
    ElMessage.error('权限不足')
    return
  }
  saving.value = true
  try {
    await updateNotificationConfig({ config: configData.value })
    ElMessage.success('已保存')
    await loadData()
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

function openGlobalDrawer() {
  globalJsonText.value = JSON.stringify(configData.value, null, 2)
  globalDrawerVisible.value = true
}

async function saveGlobalFromDrawer() {
  if (!canWrite.value) return
  globalSubmitting.value = true
  try {
    const parsed = JSON.parse(globalJsonText.value || '{}')
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('JSON 必须是对象')
    }
    configData.value = normalizeConfig({ ...defaultConfig.value, ...parsed })
    ensureDefaultChannelEnabledMap(channels.value)
    await updateNotificationConfig({ config: configData.value })
    ElMessage.success('已保存')
    globalDrawerVisible.value = false
    await loadData()
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    globalSubmitting.value = false
  }
}

function openTestDialog() {
  testResults.value = []
  testDialogVisible.value = true
}

async function handleSendTestAll() {
  if (!canWrite.value) {
    ElMessage.error('权限不足')
    return
  }
  testing.value = true
  try {
    const res = await sendNotificationTest({ title: testTitle.value, content: testContent.value })
    testResults.value = res.results || []
    for (const item of testResults.value) {
      lastTests.value[item.channel] = { ok: item.ok, error: item.error }
    }
    if (!testResults.value.length) {
      ElMessage.warning('未匹配到可用渠道，请检查配置')
    } else {
      ElMessage.success('测试已触发')
    }
  } finally {
    testing.value = false
  }
}

function openChannelDrawer(channel: NotifyChannel) {
  currentChannel.value = channel
  channelDrawerVisible.value = true
}

async function handleToggleChannel(channel: NotifyChannel, value: boolean) {
  setChannelEnabled(channel.id, value)
  await saveAll()
}

async function handleSaveChannel(payload: { channel_id: string; enabled: boolean; config_patch: Record<string, any> }) {
  if (!canWrite.value) return
  channelSubmitting.value = true
  try {
    setChannelEnabled(payload.channel_id, payload.enabled)
    for (const [key, value] of Object.entries(payload.config_patch || {})) {
      configData.value[key] = value
    }
    await updateNotificationConfig({ config: configData.value })
    ElMessage.success('已保存')
    channelDrawerVisible.value = false
    await loadData()
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    channelSubmitting.value = false
  }
}

onMounted(loadData)
</script>

<template>
  <div class="shell-page" v-loading="loading">
    <div class="section-header">
      <div class="section-header__title">
        <h2>通知配置</h2>
      </div>
      <div class="toolbar__right">
        <el-button @click="loadData">刷新</el-button>
        <el-button :disabled="!canWrite" @click="openGlobalDrawer">高级配置</el-button>
        <el-button :disabled="!canWrite" @click="openTestDialog">总测试</el-button>
      </div>
    </div>

    <section class="metric-strip">
      <div class="glass-panel metric-tile">
        <div class="metric-tile__label">渠道总数</div>
        <div class="metric-tile__value">{{ summary.total }}</div>
        <div class="metric-tile__hint">已接入的通知渠道</div>
      </div>
      <div class="glass-panel metric-tile">
        <div class="metric-tile__label">已配置</div>
        <div class="metric-tile__value">{{ summary.configured }}</div>
        <div class="metric-tile__hint">满足最低配置要求</div>
      </div>
      <div class="glass-panel metric-tile">
        <div class="metric-tile__label">已启用</div>
        <div class="metric-tile__value">{{ summary.enabled }}</div>
        <div class="metric-tile__hint">当前允许发送的渠道</div>
      </div>
      <div class="glass-panel metric-tile">
        <div class="metric-tile__label">最近失败</div>
        <div class="metric-tile__value">{{ summary.last_failed }}</div>
        <div class="metric-tile__hint">基于页面内测试结果</div>
      </div>
    </section>

    <section class="channel-grid">
      <NotificationChannelCard
        v-for="channel in channels"
        :key="channel.id"
        :channel="channel"
        :config="configData"
        :enabled="channelEnabled(channel.id)"
        :configured="channelConfiguredOverride(channel)"
        :can-write="canWrite"
        :last-result="lastTests[channel.id]"
        @configure="openChannelDrawer"
        @toggle="handleToggleChannel"
      />
    </section>

    <el-dialog v-model="testDialogVisible" title="发送测试通知" width="720px">
      <div class="notify-card notify-card--dialog">
        <el-form label-position="top">
          <el-form-item label="标题">
            <el-input v-model="testTitle" :disabled="testing" />
          </el-form-item>
          <el-form-item label="内容">
            <el-input v-model="testContent" type="textarea" :rows="4" :disabled="testing" />
          </el-form-item>
        </el-form>
        <div class="notify-actions">
          <el-button :loading="testing" type="primary" :disabled="!canWrite" @click="handleSendTestAll">发送</el-button>
        </div>
      </div>

      <el-table v-if="testResults.length" :data="testResults" style="width: 100%">
        <el-table-column prop="channel" label="渠道" width="180" />
        <el-table-column prop="ok" label="结果" width="100">
          <template #default="{ row }">
            <span>{{ row.ok ? '成功' : '失败' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="error" label="错误" />
      </el-table>

      <template #footer>
        <el-button @click="testDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <NotificationChannelDrawer
      v-model="channelDrawerVisible"
      :channel="currentChannel"
      :enabled="currentChannel ? channelEnabled(currentChannel.id) : true"
      :config="configData"
      :submitting="channelSubmitting"
      @save="handleSaveChannel"
    />

    <el-drawer :model-value="globalDrawerVisible" title="通知配置" :size="isMobile ? '100%' : '640px'" @close="globalDrawerVisible = false">
      <el-form label-position="top" class="drawer-form">
        <div class="drawer-form__section">
          <div class="drawer-form__section-title">高级配置(JSON)</div>
          <el-input v-model="globalJsonText" type="textarea" :rows="16" :disabled="!canWrite" />
        </div>
      </el-form>

      <template #footer>
        <div class="drawer-form__footer">
          <el-button @click="globalDrawerVisible = false">取消</el-button>
          <el-button type="primary" :loading="globalSubmitting" :disabled="!canWrite" @click="saveGlobalFromDrawer">
            保存
          </el-button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.notify-card {
  padding: 18px;
  border-radius: 22px;
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
}

.notify-card--dialog {
  margin-bottom: 14px;
}

.notify-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 14px;
}

.channel-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 16px;
}

.global-card {
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-height: 260px;
  padding: 22px;
}

.global-card__header,
.global-card__footer {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.global-card__heading {
  min-width: 0;
  flex: 1;
}

.global-card h3 {
  margin: 0;
  overflow: hidden;
  font-size: 18px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.global-card__meta,
.global-card__hint {
  color: var(--el-text-color-secondary);
}

.global-card__meta {
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.5;
}

.global-card__status {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.global-card__body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex: 1;
}

.global-card__body-title {
  margin-bottom: 2px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--el-text-color-secondary);
}

.global-card__summary {
  padding: 10px 12px;
  border-radius: 14px;
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
  font-size: 13px;
  line-height: 1.5;
  color: var(--el-text-color-primary);
}

.global-card__hint {
  font-size: 12px;
  line-height: 1.4;
}

.global-card__actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

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

@media (max-width: 768px) {
  .channel-grid {
    grid-template-columns: 1fr;
  }

  .global-card {
    min-height: auto;
    padding: 18px;
  }
}
</style>
