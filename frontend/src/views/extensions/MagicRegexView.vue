<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'

import { deleteMagicRegexRule, fetchMagicRegexRules, upsertMagicRegexRule } from '@/api/magicRegex'
import { fetchOpenListConfig, patchOpenListConfig } from '@/api/openlist'
import { fetchResourceSearchSources, patchResourceSearchSource } from '@/api/resourceSearch'
import { fetchTMDBConfig, patchTMDBConfig } from '@/api/tmdb'
import { TASK_WRITE } from '@/constants/permissions'
import { useAuthStore } from '@/stores/auth'
import type { MagicRegexRuleSetting } from '@/types/magicRegex'
import type { OpenListConfig } from '@/types/openlist'
import type { ResourceSearchSourceItem } from '@/types/resourceSearch'
import type { TMDBConfig } from '@/types/tmdb'

const auth = useAuthStore()
const canWrite = computed(() => auth.permissions.includes(TASK_WRITE))

const loading = ref(false)
const rules = ref<MagicRegexRuleSetting[]>([])
const activeTab = ref('magic_regex')

const resourceSearch = reactive({
  loading: false,
  savingKey: '' as string,
  net: { enabled: true },
  cloudsaver: {
    enabled: false,
    server: '',
    username: '',
    token: '',
    passwordInput: '',
  },
  pansou: {
    enabled: false,
    server: '',
  },
})

const tmdb = reactive({
  loading: false,
  saving: false,
  hasApiKey: false,
  language: 'zh-CN',
  posterLanguage: 'zh-CN',
  apiKeyInput: '',
  enableGuessitFallbackRename: true,
  tvRenameTemplate: '{title}.S{season}E{episode}{ext}',
  movieRenameTemplate: '{title_dot}.{year}{ext}',
})

const openlist = reactive({
  loading: false,
  saving: false,
  url: '',
  hasToken: false,
  tokenInput: '',
})

const builtinKeySet = computed(() => new Set(rules.value.filter((r) => r.built_in).map((r) => r.key)))
const currentIsBuiltinKey = computed(() => builtinKeySet.value.has(normalizeKey(dialog.form.key)))

const dialog = reactive({
  visible: false,
  submitting: false,
  isEdit: false,
  keyLocked: false,
  form: {
    key: '',
    label: '' as string | null,
    enabled: true,
    pattern: '',
    replace: '',
  },
})

function normalizeKey(key: string) {
  return String(key || '').trim()
}

function isValidKey(key: string) {
  const value = normalizeKey(key)
  return value.startsWith('$') && !value.includes(' ') && value.length <= 64
}

async function refresh() {
  loading.value = true
  try {
    const data = await fetchMagicRegexRules()
    rules.value = data.rules || []
  } finally {
    loading.value = false
  }
}

function findSource(list: ResourceSearchSourceItem[], key: string) {
  return list.find((x) => x.key === key) || null
}

function applySources(list: ResourceSearchSourceItem[]) {
  const net = findSource(list, 'net')
  if (net) {
    resourceSearch.net.enabled = Boolean(net.enabled)
  }
  const cs = findSource(list, 'cloudsaver')
  if (cs) {
    resourceSearch.cloudsaver.enabled = Boolean(cs.enabled)
    resourceSearch.cloudsaver.server = String(cs.server || '')
    resourceSearch.cloudsaver.username = String(cs.username || '')
    resourceSearch.cloudsaver.token = String(cs.token || '')
  }
  const ps = findSource(list, 'pansou')
  if (ps) {
    resourceSearch.pansou.enabled = Boolean(ps.enabled)
    resourceSearch.pansou.server = String(ps.server || '')
  }
}

async function refreshSources() {
  resourceSearch.loading = true
  try {
    const data = await fetchResourceSearchSources()
    applySources(data.sources || [])
  } finally {
    resourceSearch.loading = false
  }
}

function applyTMDBConfig(data: TMDBConfig) {
  tmdb.hasApiKey = Boolean(data.has_api_key)
  tmdb.language = String(data.language || 'zh-CN')
  tmdb.posterLanguage = String(data.poster_language || 'zh-CN')
  tmdb.enableGuessitFallbackRename = !Boolean(data.disable_guessit_tmdb_fallback_rename)
  tmdb.tvRenameTemplate = String(data.guessit_tmdb_tv_rename_template || '{title}.S{season}E{episode}{ext}')
  tmdb.movieRenameTemplate = String(data.guessit_tmdb_movie_rename_template || '{title_dot}.{year}{ext}')
}

async function refreshTMDB() {
  tmdb.loading = true
  try {
    const data = await fetchTMDBConfig()
    applyTMDBConfig(data)
  } finally {
    tmdb.loading = false
  }
}

function applyOpenListConfig(data: OpenListConfig) {
  openlist.url = String(data.url || '')
  openlist.hasToken = Boolean(data.has_token)
}

async function refreshOpenList() {
  openlist.loading = true
  try {
    const data = await fetchOpenListConfig()
    applyOpenListConfig(data)
  } finally {
    openlist.loading = false
  }
}

async function saveOpenList() {
  if (!canWrite.value) return
  openlist.saving = true
  try {
    const payload: any = {
      url: openlist.url ? String(openlist.url).trim() : null,
    }
    const token = String(openlist.tokenInput || '').trim()
    if (token) payload.token = token
    const data = await patchOpenListConfig(payload)
    openlist.tokenInput = ''
    applyOpenListConfig(data)
    ElMessage.success('已保存')
  } finally {
    openlist.saving = false
  }
}

async function saveTMDB() {
  if (!canWrite.value) return
  tmdb.saving = true
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
    tmdb.saving = false
  }
}

function useDefaultRenameTemplates() {
  tmdb.tvRenameTemplate = '{title}.S{season}E{episode}{ext}'
  tmdb.movieRenameTemplate = '{title_dot}.{year}{ext}'
}

async function saveSource(key: 'net' | 'cloudsaver' | 'pansou') {
  if (!canWrite.value) return
  resourceSearch.savingKey = key
  try {
    if (key === 'net') {
      await patchResourceSearchSource('net', { enabled: Boolean(resourceSearch.net.enabled) })
      ElMessage.success('已保存')
      await refreshSources()
      return
    }
    if (key === 'pansou') {
      await patchResourceSearchSource('pansou', {
        enabled: Boolean(resourceSearch.pansou.enabled),
        server: resourceSearch.pansou.server ? String(resourceSearch.pansou.server).trim() : null,
      })
      ElMessage.success('已保存')
      await refreshSources()
      return
    }

    const payload: any = {
      enabled: Boolean(resourceSearch.cloudsaver.enabled),
      server: resourceSearch.cloudsaver.server ? String(resourceSearch.cloudsaver.server).trim() : null,
      username: resourceSearch.cloudsaver.username ? String(resourceSearch.cloudsaver.username).trim() : null,
    }
    const pw = String(resourceSearch.cloudsaver.passwordInput || '')
    if (pw.trim()) payload.password = pw
    await patchResourceSearchSource('cloudsaver', payload)
    resourceSearch.cloudsaver.passwordInput = ''
    ElMessage.success('已保存')
    await refreshSources()
  } finally {
    resourceSearch.savingKey = ''
  }
}

function openCreate() {
  dialog.visible = true
  dialog.submitting = false
  dialog.isEdit = false
  dialog.keyLocked = false
  dialog.form.key = '$'
  dialog.form.label = null
  dialog.form.enabled = true
  dialog.form.pattern = ''
  dialog.form.replace = ''
}

function openEdit(rule: MagicRegexRuleSetting) {
  dialog.visible = true
  dialog.submitting = false
  dialog.isEdit = true
  dialog.keyLocked = true
  dialog.form.key = rule.key
  dialog.form.label = rule.label ?? null
  dialog.form.enabled = Boolean(rule.enabled)
  dialog.form.pattern = rule.pattern || ''
  dialog.form.replace = rule.replace || ''
}

async function submit() {
  const key = normalizeKey(dialog.form.key)
  if (!isValidKey(key)) {
    ElMessage.warning('key 必须以 $ 开头，且不能包含空格（最长 64）')
    return
  }
  if (!dialog.isEdit) {
    if (!String(dialog.form.pattern || '').trim()) {
      ElMessage.warning('新增规则时 pattern 不能为空')
      return
    }
  }
  dialog.submitting = true
  try {
    const data = await upsertMagicRegexRule(key, {
      label: dialog.form.label ? String(dialog.form.label).trim() : null,
      enabled: Boolean(dialog.form.enabled),
      pattern: String(dialog.form.pattern || '').trim() || null,
      replace: String(dialog.form.replace || ''),
    })
    rules.value = data.rules || []
    dialog.visible = false
    ElMessage.success('已保存')
  } finally {
    dialog.submitting = false
  }
}

async function toggleCustom(rule: MagicRegexRuleSetting, value: boolean) {
  if (!canWrite.value) return
  if (rule.built_in) return
  const key = normalizeKey(rule.key)
  try {
    const data = await upsertMagicRegexRule(key, { enabled: Boolean(value) })
    rules.value = data.rules || []
  } catch {
    await refresh()
  }
}

async function removeRule(rule: MagicRegexRuleSetting) {
  if (!canWrite.value) return
  const title = rule.built_in ? '恢复默认规则' : '删除自定义规则'
  const message = rule.built_in
    ? `将清除对 ${rule.key} 的覆盖配置，恢复为系统默认值。`
    : `将删除 ${rule.key} 规则。`
  try {
    await ElMessageBox.confirm(message, title, { type: 'warning', confirmButtonText: '确认', cancelButtonText: '取消' })
  } catch {
    return
  }
  const data = await deleteMagicRegexRule(rule.key)
  rules.value = data.rules || []
  ElMessage.success('已更新')
}

const builtinRules = computed(() => rules.value.filter((r) => r.built_in))
const customRules = computed(() => rules.value.filter((r) => !r.built_in))

onMounted(() => {
  refresh()
  refreshSources()
  refreshTMDB()
  refreshOpenList()
})
</script>

<template>
  <div class="page">
    <div class="page__header">
      <div class="page__title">系统设置</div>
      <div class="page__actions">
        <el-button v-if="activeTab === 'magic_regex'" type="primary" :disabled="!canWrite" @click="openCreate">新增规则</el-button>
      </div>
    </div>

    <el-tabs v-model="activeTab">
      <el-tab-pane label="保存规则" name="magic_regex">
        <div class="page__hint">
          <div>新增的规则 key 需要以 $ 开头（例如：$MY_RULE）。在追剧任务里将 pattern 设置为该 key，即可使用系统保存规则。</div>
          <div>replace 为默认模板；任务里 replace 留空时，会自动使用该默认值。</div>
        </div>

        <el-card class="page__card" shadow="never">
          <template #header>
            <div class="card__header">
              <div>内置规则</div>
              <el-button text :loading="loading" @click="refresh">刷新</el-button>
            </div>
          </template>
          <el-table :data="builtinRules" :loading="loading" style="width: 100%">
            <el-table-column prop="key" label="key" width="180" />
            <el-table-column prop="label" label="名称" min-width="160" />
            <el-table-column label="状态" width="140">
              <template #default="{ row }">
                <el-tag v-if="row.overridden" type="warning">已覆盖</el-tag>
                <el-tag v-else type="info">默认</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="pattern" min-width="240" show-overflow-tooltip>
              <template #default="{ row }">{{ row.pattern }}</template>
            </el-table-column>
            <el-table-column label="replace" min-width="240" show-overflow-tooltip>
              <template #default="{ row }">{{ row.replace }}</template>
            </el-table-column>
            <el-table-column label="操作" width="200">
              <template #default="{ row }">
                <el-button size="small" :disabled="!canWrite" @click="openEdit(row)">编辑</el-button>
                <el-button size="small" :disabled="!canWrite || !row.overridden" @click="removeRule(row)">恢复默认</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <el-card class="page__card" shadow="never">
          <template #header>
            <div class="card__header">
              <div>自定义规则</div>
            </div>
          </template>
          <el-table :data="customRules" :loading="loading" style="width: 100%">
            <el-table-column prop="key" label="key" width="180" />
            <el-table-column prop="label" label="名称" min-width="160" />
            <el-table-column label="启用" width="120">
              <template #default="{ row }">
                <el-switch :model-value="row.enabled" :disabled="!canWrite" @change="(v: any) => toggleCustom(row, v)" />
              </template>
            </el-table-column>
            <el-table-column label="pattern" min-width="240" show-overflow-tooltip>
              <template #default="{ row }">{{ row.pattern }}</template>
            </el-table-column>
            <el-table-column label="replace" min-width="240" show-overflow-tooltip>
              <template #default="{ row }">{{ row.replace }}</template>
            </el-table-column>
            <el-table-column label="操作" width="160">
              <template #default="{ row }">
                <el-button size="small" :disabled="!canWrite" @click="openEdit(row)">编辑</el-button>
                <el-button size="small" type="danger" :disabled="!canWrite" @click="removeRule(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="资源搜索" name="resource_search">
        <div class="page__hint">
          <div>任务名称输入框会使用这里的搜索源进行资源建议。</div>
          <div>CloudSaver 密码不回显；如需修改请重新输入后保存。</div>
        </div>

        <el-card class="page__card" shadow="never">
          <template #header>
            <div class="card__header">
              <div>网络公开搜索</div>
              <div>
                <el-button text :loading="resourceSearch.loading" @click="refreshSources">刷新</el-button>
                <el-button type="primary" :loading="resourceSearch.savingKey === 'net'" :disabled="!canWrite" @click="saveSource('net')">保存</el-button>
              </div>
            </div>
          </template>
          <el-form label-position="top" :disabled="resourceSearch.loading">
            <el-form-item label="启用">
              <el-switch v-model="resourceSearch.net.enabled" :disabled="!canWrite" />
            </el-form-item>
          </el-form>
        </el-card>

        <el-card class="page__card" shadow="never">
          <template #header>
            <div class="card__header">
              <div>CloudSaver</div>
              <el-button type="primary" :loading="resourceSearch.savingKey === 'cloudsaver'" :disabled="!canWrite" @click="saveSource('cloudsaver')">
                保存
              </el-button>
            </div>
          </template>
          <el-form label-position="top" :disabled="resourceSearch.loading">
            <el-form-item label="启用">
              <el-switch v-model="resourceSearch.cloudsaver.enabled" :disabled="!canWrite" />
            </el-form-item>
            <el-form-item label="服务器">
              <el-input v-model="resourceSearch.cloudsaver.server" placeholder="例如：http://172.17.0.1:8008" />
            </el-form-item>
            <el-form-item label="用户名">
              <el-input v-model="resourceSearch.cloudsaver.username" placeholder="用户名" />
            </el-form-item>
            <el-form-item label="密码（留空表示不修改）">
              <el-input v-model="resourceSearch.cloudsaver.passwordInput" type="password" show-password placeholder="请输入新密码" />
            </el-form-item>
            <el-form-item label="Token（自动维护）">
              <el-input v-model="resourceSearch.cloudsaver.token" disabled placeholder="自动登录后会写入 token" />
            </el-form-item>
          </el-form>
        </el-card>

        <el-card class="page__card" shadow="never">
          <template #header>
            <div class="card__header">
              <div>PanSou</div>
              <el-button type="primary" :loading="resourceSearch.savingKey === 'pansou'" :disabled="!canWrite" @click="saveSource('pansou')">保存</el-button>
            </div>
          </template>
          <el-form label-position="top" :disabled="resourceSearch.loading">
            <el-form-item label="启用">
              <el-switch v-model="resourceSearch.pansou.enabled" :disabled="!canWrite" />
            </el-form-item>
            <el-form-item label="服务器">
              <el-input v-model="resourceSearch.pansou.server" placeholder="例如：https://so.252035.xyz" />
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="TMDB" name="tmdb">
        <div class="page__hint">
          <div>用于影视发现页的 TMDB 信息补全与搜索。</div>
          <div>API Key 不回显；留空保存表示不修改。</div>
        </div>

        <el-card class="page__card" shadow="never">
          <template #header>
            <div class="card__header">
              <div>TMDB 配置</div>
              <div>
                <el-button text :loading="tmdb.loading" @click="refreshTMDB">刷新</el-button>
                <el-button text :disabled="tmdb.loading" @click="useDefaultRenameTemplates">默认模板</el-button>
                <el-button type="primary" :loading="tmdb.saving" :disabled="!canWrite" @click="saveTMDB">保存</el-button>
              </div>
            </div>
          </template>

          <el-form label-position="top" :disabled="tmdb.loading">
            <el-form-item label="API Key（留空不修改）">
              <el-input v-model="tmdb.apiKeyInput" type="password" show-password :placeholder="tmdb.hasApiKey ? '已配置（留空不修改）' : '请输入 TMDB API Key'" />
            </el-form-item>
            <el-form-item label="语言（language）">
              <el-select v-model="tmdb.language" style="width: 260px">
                <el-option label="中文（zh-CN）" value="zh-CN" />
                <el-option label="英文（en-US）" value="en-US" />
              </el-select>
            </el-form-item>
            <el-form-item label="海报语言（poster_language）">
              <el-select v-model="tmdb.posterLanguage" style="width: 260px">
                <el-option label="中文（zh-CN）" value="zh-CN" />
                <el-option label="原始语言（original）" value="original" />
              </el-select>
            </el-form-item>
            <el-form-item label="启用 guessit+TMDB 兜底重命名">
              <el-switch v-model="tmdb.enableGuessitFallbackRename" :disabled="!canWrite || !tmdb.hasApiKey" />
              <div class="page__hint">
                <div>开启后，追剧任务在 pattern/replace 为空时将按下方模板自动生成目标文件名（不会影响手动配置的保存规则）。</div>
              </div>
            </el-form-item>
            <el-form-item label="电视剧兜底命名模板（TV）">
              <el-input
                v-model="tmdb.tvRenameTemplate"
                type="textarea"
                :rows="2"
                :disabled="!tmdb.hasApiKey"
                placeholder="{title}.S{season}E{episode}{ext}"
              />
              <div class="page__hint">
                <div>可用占位符：</div>
                <div>- {title}：标题（空格分隔）</div>
                <div>- {title_dot}：标题（点分隔）</div>
                <div>- {season}：季（两位数，如 01）</div>
                <div>- {episode}：集（两位数，如 02）</div>
                <div>- {season_num}：季（原始数字，如 1）</div>
                <div>- {episode_num}：集（原始数字，如 2）</div>
                <div>- {year}：年份（通常为空；为兼容模板保留）</div>
                <div>- {ext}：扩展名（包含 .，如 .mkv；若模板不写 {ext} 会自动补上）</div>
                <div>- {orig}：原始文件名（含扩展名）</div>
                <div>- {orig_base}：原始文件名（不含扩展名）</div>
                <div>- {orig_base_dot}：orig_base 的点分隔形式</div>
                <div>- {tags_dot}：清洗后的资源标签（点分隔，可能为空）</div>
                <div>- {tags_space}：清洗后的资源标签（空格分隔，可能为空）</div>
                <div>示例：{title}.S{season}E{episode}{ext} → 低智商犯罪.S01E02.mp4</div>
              </div>
            </el-form-item>
            <el-form-item label="电影兜底命名模板（Movie）">
              <el-input
                v-model="tmdb.movieRenameTemplate"
                type="textarea"
                :rows="2"
                :disabled="!tmdb.hasApiKey"
                placeholder="{title_dot}.{year}{ext}"
              />
              <div class="page__hint">
                <div>可用占位符：</div>
                <div>- {title}：标题（空格分隔）</div>
                <div>- {title_dot}：标题（点分隔）</div>
                <div>- {year}：年份（可能为空；为空时会自动清理多余的点/空格/空括号）</div>
                <div>- {ext}：扩展名（包含 .，如 .mkv；若模板不写 {ext} 会自动补上）</div>
                <div>- {orig}：原始文件名（含扩展名）</div>
                <div>- {orig_base}：原始文件名（不含扩展名）</div>
                <div>- {orig_base_dot}：orig_base 的点分隔形式</div>
                <div>- {tags_dot}：清洗后的资源标签（点分隔，可能为空）</div>
                <div>- {tags_space}：清洗后的资源标签（空格分隔，可能为空）</div>
                <div>示例：{title_dot}.{year}{ext} → The.World.of.Love.2025.mkv</div>
              </div>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="OpenList" name="openlist">
        <div class="page__hint">
          <div>用于同步任务等功能的 OpenList 连接配置。</div>
          <div>Token 不回显；留空保存表示不修改。</div>
        </div>

        <el-card class="page__card" shadow="never">
          <template #header>
            <div class="card__header">
              <div>OpenList 配置</div>
              <div>
                <el-button text :loading="openlist.loading" @click="refreshOpenList">刷新</el-button>
                <el-button type="primary" :loading="openlist.saving" :disabled="!canWrite" @click="saveOpenList">保存</el-button>
              </div>
            </div>
          </template>

          <el-form label-position="top" :disabled="openlist.loading">
            <el-form-item label="地址（url）">
              <el-input v-model="openlist.url" placeholder="例如：http://172.17.0.1:5244" />
            </el-form-item>
            <el-form-item label="Token（留空不修改）">
              <el-input
                v-model="openlist.tokenInput"
                type="password"
                show-password
                :placeholder="openlist.hasToken ? '已配置（留空不修改）' : '请输入 OpenList Token'"
              />
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="dialog.visible" :title="dialog.isEdit ? '编辑规则' : '新增规则'" width="720px">
      <el-form label-position="top">
        <el-form-item label="key（以 $ 开头）">
          <el-input v-model="dialog.form.key" :disabled="dialog.keyLocked" placeholder="$MY_RULE" />
        </el-form-item>
        <el-form-item label="名称（可选）">
          <el-input v-model="dialog.form.label" placeholder="例如：综艺命名（含日期）" />
        </el-form-item>
        <el-form-item v-if="!dialog.form.key || !String(dialog.form.key).startsWith('$')" label="提示">
          <div class="page__hint">key 必须以 $ 开头。</div>
        </el-form-item>
        <el-form-item v-if="!currentIsBuiltinKey" label="启用">
          <el-switch v-model="dialog.form.enabled" :disabled="!canWrite" />
        </el-form-item>
        <el-form-item label="pattern（正则表达式）">
          <el-input v-model="dialog.form.pattern" type="textarea" :rows="4" placeholder="例如：^(?!.*纯享).*?第\\d+期.*" />
        </el-form-item>
        <el-form-item label="replace（默认替换模板）">
          <el-input v-model="dialog.form.replace" type="textarea" :rows="3" placeholder="{II}.{TASKNAME}.{DATE}.第{E}期{PART}.{EXT}" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="dialog.submitting" :disabled="!canWrite" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page {
  padding: 16px;
}
.page__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.page__title {
  font-size: 18px;
  font-weight: 600;
}
.page__actions {
  display: flex;
  gap: 8px;
}
.page__hint {
  margin: 10px 0 14px;
  color: var(--el-text-color-regular);
  font-size: 13px;
  line-height: 1.7;
}
.page__card {
  margin-bottom: 14px;
}
.card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
