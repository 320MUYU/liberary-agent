<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { notificationTarget } from '@/notificationApi'
import { useNotifications } from '@/store/notificationStore'
import { formatLoanTime } from '@/utils/library.js'

const router = useRouter()
const { recent, unreadCount, loading, stale, refresh, read } = useNotifications()
const visible = ref(false)
const busy = ref(false)

function showAll() {
  visible.value = false
  router.push('/notifications')
}

async function open(item) {
  if (busy.value) return
  busy.value = true
  try {
    if (!(await read(item.id))) return
    visible.value = false
    router.push(notificationTarget(item))
  } catch {
    /* 请求层提示失败，可重试。 */
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <el-popover
    v-model:visible="visible"
    placement="bottom-end"
    :width="330"
    trigger="click"
    @show="refresh"
  >
    <template #reference>
      <button class="reader-bell" :aria-label="`消息通知，${unreadCount} 条未读`">
        <el-icon><Bell /></el-icon>
        <span v-if="unreadCount" class="count">{{ unreadCount > 99 ? '99+' : unreadCount }}</span>
      </button>
    </template>
    <section class="reader-inbox" aria-label="最近通知">
      <div class="inbox-head">
        <strong>消息通知</strong><span>{{ unreadCount }} 条未读</span>
      </div>
      <p v-if="stale" class="inbox-error" role="status">通知未更新，请刷新重试。</p>
      <button
        v-for="item in recent"
        :key="item.id"
        class="notice"
        :class="{ unread: !item.read_at }"
        :disabled="busy"
        @click="open(item)"
      >
        <strong>{{ item.title }}<i v-if="!item.read_at" aria-label="未读"></i></strong>
        <p>{{ item.content }}</p>
        <small>{{ formatLoanTime(item.create_time) }}</small>
      </button>
      <p v-if="!recent.length">
        {{ loading ? '正在读取通知…' : stale ? '通知暂不可用' : '暂无通知' }}
      </p>
      <div class="inbox-footer">
        <el-button text :loading="loading" @click="refresh">刷新</el-button
        ><el-button text type="primary" @click="showAll">查看全部</el-button>
      </div>
    </section>
  </el-popover>
</template>

<style scoped>
.reader-bell {
  position: relative;
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border: 0;
  border-radius: 10px;
  background: #f1f5f3;
  color: #526c67;
  cursor: pointer;
  font-size: 19px;
}
.count {
  position: absolute;
  top: -5px;
  right: -8px;
  min-width: 19px;
  padding: 2px 4px;
  border-radius: 12px;
  background: #b75143;
  color: white;
  font-size: 10px;
}
.inbox-head,
.inbox-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.inbox-head span,
small {
  color: #7b8b86;
  font-size: 12px;
}
.notice {
  width: 100%;
  padding: 14px 8px;
  text-align: left;
  background: transparent;
  border: 0;
  border-bottom: 1px solid #edf0ec;
  color: #29443d;
  cursor: pointer;
}
.notice.unread {
  background: #f1f8f4;
}
.notice strong {
  display: flex;
  align-items: center;
  gap: 8px;
}
.notice i {
  width: 6px;
  height: 6px;
  background: #2d8174;
  border-radius: 50%;
}
.notice p {
  margin: 6px 0;
  font-size: 12px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}
.inbox-error {
  color: #a85535;
}
.inbox-footer {
  padding-top: 8px;
}
</style>
