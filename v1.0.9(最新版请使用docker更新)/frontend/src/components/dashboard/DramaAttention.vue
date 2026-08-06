<script setup lang="ts">
import type { DramaFailureItem } from '@/types/dashboard'
import type { TaskItem } from '@/types/tasks'
import { formatDateTime } from '@/utils/capacity'

const props = defineProps<{
  recentFailures: DramaFailureItem[]
  tasks: TaskItem[]
}>()

const showAllFailures = ref(false)

const failures = computed(() => {
  return props.recentFailures
    .filter((it) => String(it.status || '').toLowerCase() === 'failed')
})

const displayFailures = computed(() => failures.value.slice(0, 3))
const hiddenFailures = computed(() => failures.value.slice(3))

const todoItems = computed(() => {
  const items: Array<{ taskId: number; title: string; reason: string }> = []
  for (const task of props.tasks) {
    if (task.task_type !== 'drama') continue
    if (!task.enabled) continue

    const ban = String(task.shareurl_ban || '').trim()
    if (ban) {
      items.push({ taskId: task.id, title: String(task.taskname || '').trim() || `任务 #${task.id}`, reason: `已封禁：${ban}` })
      continue
    }

    const tmdbId = task.tmdb_id
    const runweek = Array.isArray(task.extra?.runweek) ? task.extra.runweek : []
    const validWeekdays = runweek.map((x: any) => Number(x)).filter((x: number) => x >= 1 && x <= 7)
    if (!tmdbId && validWeekdays.length === 0) {
      items.push({ taskId: task.id, title: String(task.taskname || '').trim() || `任务 #${task.id}`, reason: '未绑定 TMDB 且未配置更新日' })
    }
  }
  return items.slice(0, 12)
})

function labelOfStatus(status: string) {
  const s = String(status || '').toLowerCase()
  if (s === 'failed') return '失败'
  if (s === 'success') return '成功'
  return s || '--'
}

function tagTypeOfStatus(status: string) {
  const s = String(status || '').toLowerCase()
  if (s === 'failed') return 'danger'
  if (s === 'success') return 'success'
  return 'info'
}
</script>

<template>
  <div class="attention-grid">
    <section class="glass-panel attention-card">
      <div class="group-stack__title">
        <h3>近期失败</h3>
        <span class="status-pill" :class="failures.length ? 'status-pill--danger' : 'status-pill--success'">
          {{ failures.length ? `${failures.length} 条` : '暂无' }}
        </span>
      </div>

      <el-empty v-if="!displayFailures.length" description="近期开启后没有失败记录。" :image-size="88" />

      <div v-else class="list">
        <div v-for="item in displayFailures" :key="`${item.task_id}-${item.started_at}`" class="list-row">
          <div class="list-row__main">
            <div class="list-row__title">
              <span class="title">{{ item.taskname }}</span>
              <el-tag size="small" :type="tagTypeOfStatus(item.status)">{{ labelOfStatus(item.status) }}</el-tag>
            </div>
            <div class="list-row__meta">
              <span>{{ formatDateTime(item.started_at) }}</span>
              <span v-if="item.stage" class="meta-dot">·</span>
              <span v-if="item.stage">阶段 {{ item.stage }}</span>
            </div>
            <div v-if="item.message" class="list-row__message">{{ item.message }}</div>
          </div>
          <div class="list-row__side">
            <router-link to="/tasks/drama">
              <el-button size="small">查看</el-button>
            </router-link>
          </div>
        </div>

        <el-collapse-transition>
          <div v-if="showAllFailures && hiddenFailures.length" class="list">
            <div v-for="item in hiddenFailures" :key="`${item.task_id}-${item.started_at}`" class="list-row">
              <div class="list-row__main">
                <div class="list-row__title">
                  <span class="title">{{ item.taskname }}</span>
                  <el-tag size="small" :type="tagTypeOfStatus(item.status)">{{ labelOfStatus(item.status) }}</el-tag>
                </div>
                <div class="list-row__meta">
                  <span>{{ formatDateTime(item.started_at) }}</span>
                  <span v-if="item.stage" class="meta-dot">·</span>
                  <span v-if="item.stage">阶段 {{ item.stage }}</span>
                </div>
                <div v-if="item.message" class="list-row__message">{{ item.message }}</div>
              </div>
              <div class="list-row__side">
                <router-link to="/tasks/drama">
                  <el-button size="small">查看</el-button>
                </router-link>
              </div>
            </div>
          </div>
        </el-collapse-transition>

        <div v-if="hiddenFailures.length" class="more-row">
          <el-button size="small" text @click="showAllFailures = !showAllFailures">
            {{ showAllFailures ? '收起' : `展开更多（${hiddenFailures.length}）` }}
          </el-button>
        </div>
      </div>
    </section>

    <section class="glass-panel attention-card">
      <div class="group-stack__title">
        <h3>待完善任务</h3>
        <span class="status-pill" :class="todoItems.length ? 'status-pill--danger' : 'status-pill--success'">
          {{ todoItems.length ? `${todoItems.length} 项` : '暂无' }}
        </span>
      </div>

      <el-empty v-if="!todoItems.length" description="启用任务已具备更新日配置且无封禁项。" :image-size="88" />

      <div v-else class="list">
        <div v-for="it in todoItems" :key="it.taskId" class="list-row">
          <div class="list-row__main">
            <div class="list-row__title">
              <span class="title">{{ it.title }}</span>
            </div>
            <div class="list-row__message">{{ it.reason }}</div>
          </div>
          <div class="list-row__side">
            <router-link to="/tasks/drama">
              <el-button size="small">去配置</el-button>
            </router-link>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.attention-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
}

.attention-card {
  padding: 22px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.list-row {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  padding: 14px;
  border-radius: 18px;
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
}

.list-row__title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 650;
}

.title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 360px;
}

.list-row__meta {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.meta-dot {
  margin: 0 6px;
  color: var(--el-text-color-secondary);
}

.list-row__message {
  margin-top: 8px;
  font-size: 13px;
  color: var(--el-text-color-regular);
  line-height: 1.5;
  word-break: break-word;
}

.list-row__side {
  display: flex;
  align-items: start;
}

.more-row {
  display: flex;
  justify-content: center;
  padding-top: 2px;
}

@media (max-width: 1100px) {
  .attention-grid {
    grid-template-columns: 1fr;
  }

  .title {
    max-width: 220px;
  }
}
</style>
