<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { getToken, getUserInfo } from '@/auth'
import { getNotificationsApi, notificationTarget } from '@/notificationApi'
import { useNotifications } from '@/store/notificationStore'
import { formatLoanTime } from '@/utils/library.js'

const router = useRouter()
const { revision, read, readAll } = useNotifications()
const items = ref([])
const total = ref(0)
const unreadCount = ref(0)
const maxId = ref(0)
const page = ref(1)
const unreadOnly = ref(false)
const loading = ref(false)
const failed = ref(false)
const busy = ref(false)
let sequence = 0

async function fetchPage() {
  const current = ++sequence
  const token = getToken()
  const owner = getUserInfo()?.id
  loading.value = true
  failed.value = false
  try {
    const data = await getNotificationsApi({
      page: page.value,
      page_size: 10,
      unread_only: unreadOnly.value
    })
    if (current !== sequence || getToken() !== token || getUserInfo()?.id !== owner) return
    if (page.value > 1 && !data.items.length) {
      page.value = Math.max(1, Math.ceil(data.total / 10))
      return fetchPage()
    }
    items.value = data.items
    total.value = data.total
    unreadCount.value = data.unread_count
    maxId.value = data.max_id
  } catch {
    if (current === sequence) failed.value = true
  } finally {
    if (current === sequence) loading.value = false
  }
}

function changeFilter() {
  page.value = 1
  fetchPage()
}

async function act(item, navigate = false) {
  if (busy.value) return
  busy.value = true
  try {
    if (!(await read(item.id))) return
    if (navigate) router.push(notificationTarget(item))
    else await fetchPage()
  } catch {
    /* 请求层已提示，可重试。 */
  } finally {
    busy.value = false
  }
}

async function markAll() {
  if (busy.value || !maxId.value) return
  const boundary = maxId.value
  busy.value = true
  try {
    if (await readAll(boundary)) await fetchPage()
  } catch {
    /* 请求层已提示，可重试。 */
  } finally {
    busy.value = false
  }
}

watch(revision, fetchPage)
onMounted(fetchPage)
onUnmounted(() => {
  sequence++
})
</script>

<template>
  <section class="notifications-page surface">
    <div class="notification-heading">
      <div>
        <h2>消息通知</h2>
        <p>{{ unreadCount }} 条未读 · 借阅与预约进度</p>
      </div>
      <el-button :disabled="busy || loading || !unreadCount" @click="markAll"
        >全部标为已读</el-button
      >
    </div>
    <div class="notification-toolbar">
      <el-switch v-model="unreadOnly" active-text="只看未读" @change="changeFilter" /><el-button
        :loading="loading"
        @click="fetchPage"
        >刷新</el-button
      >
    </div>
    <el-alert
      v-if="failed"
      title="通知加载失败，请刷新重试。"
      type="error"
      :closable="false"
      show-icon
    />
    <div v-loading="loading" class="notification-list">
      <article
        v-for="item in items"
        :key="item.id"
        class="notification-row"
        :class="{ unread: !item.read_at }"
      >
        <div class="notification-copy">
          <h3>{{ item.title }} <el-tag v-if="!item.read_at" size="small">未读</el-tag></h3>
          <p>{{ item.content }}</p>
          <small>{{ formatLoanTime(item.create_time) }}</small>
        </div>
        <div class="notification-actions">
          <el-button :disabled="busy" @click="act(item, true)">查看详情</el-button
          ><el-button v-if="!item.read_at" text type="primary" :disabled="busy" @click="act(item)"
            >标为已读</el-button
          >
        </div>
      </article>
      <el-empty
        v-if="!loading && !failed && !items.length"
        :description="unreadOnly ? '没有未读通知' : '暂无通知，业务进度更新后会显示在这里'"
      />
    </div>
    <el-pagination
      v-if="total"
      v-model:current-page="page"
      :page-size="10"
      :total="total"
      layout="prev, pager, next"
      @current-change="fetchPage"
    />
  </section>
</template>

<style scoped>
.notifications-page {
  padding: 28px;
}
.notification-heading,
.notification-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}
h2 {
  color: var(--ink);
  font-size: 23px;
}
.notification-heading p {
  margin-top: 6px;
  color: #71857d;
  font-size: 13px;
}
.notification-row {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 20px;
  border-bottom: 1px solid #e6ece6;
}
.notification-row.unread {
  background: #f0f7f2;
}
.notification-copy {
  flex: 1;
  min-width: 0;
}
h3 {
  display: flex;
  align-items: center;
  gap: 9px;
  font-size: 15px;
  color: #29443d;
}
.notification-copy p {
  margin: 9px 0;
  line-height: 1.7;
  font-size: 13px;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
small {
  color: #7b8b86;
}
.notification-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.el-pagination {
  margin-top: 22px;
  justify-content: center;
}
@media (max-width: 700px) {
  .notifications-page {
    padding: 16px;
  }
  .notification-heading {
    align-items: flex-start;
    flex-direction: column;
  }
  .notification-row {
    align-items: stretch;
    flex-direction: column;
    gap: 12px;
    padding: 16px 10px;
  }
}
</style>
