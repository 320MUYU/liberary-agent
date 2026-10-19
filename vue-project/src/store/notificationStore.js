import { ref, readonly } from 'vue'
import { getToken, getUserInfo } from '@/auth'
import {
  getNotificationsApi,
  readNotificationApi,
  readAllNotificationsApi
} from '@/notificationApi'

const recent = ref([])
const unreadCount = ref(0)
const maxId = ref(0)
const loading = ref(false)
const stale = ref(false)
const revision = ref(0)
let owner = null
let ownerToken = null
let generation = 0
let pending = null
let timer = null

function authorized(userId = owner, token = ownerToken) {
  return (
    !!token &&
    getToken() === token &&
    getUserInfo()?.id === userId &&
    getUserInfo()?.role !== 'admin'
  )
}

function refresh({ afterWrite = false } = {}) {
  if (!authorized()) return Promise.resolve()
  if (pending && afterWrite) {
    const current = generation
    return pending.then(() => (current === generation ? refresh() : undefined))
  }
  if (pending) return pending
  const current = generation
  loading.value = true
  const request = Promise.resolve().then(async () => {
    try {
      if (current !== generation || !authorized()) return
      const data = await getNotificationsApi({ page: 1, page_size: 5 })
      if (current !== generation || !authorized()) return
      recent.value = data.items
      unreadCount.value = data.unread_count
      maxId.value = data.max_id
      stale.value = false
      revision.value++
    } catch {
      if (current === generation && authorized()) stale.value = true
    } finally {
      if (current === generation) loading.value = false
      if (pending === request) pending = null
    }
  })
  pending = request
  return request
}

async function write(action) {
  if (!authorized()) return false
  const current = generation
  await action()
  if (current !== generation || !authorized()) return false
  await refresh({ afterWrite: true })
  if (current !== generation || !authorized()) return false
  // Notify the full list even when its follow-up bell request failed.
  revision.value++
  return true
}

function read(id) {
  return write(() => readNotificationApi(id))
}

function readAll(throughId) {
  return write(() => readAllNotificationsApi(throughId))
}

function focus() {
  if (document.visibilityState === 'visible') return refresh()
}

function stop() {
  generation++
  owner = null
  ownerToken = null
  pending = null
  recent.value = []
  unreadCount.value = 0
  maxId.value = 0
  loading.value = false
  stale.value = false
  if (timer) clearInterval(timer)
  timer = null
  window.removeEventListener('focus', focus)
  window.removeEventListener('labmind:logout', stop)
  document.removeEventListener('visibilitychange', focus)
}

function start(userId) {
  const token = getToken()
  if (!authorized(userId, token)) {
    stop()
    return Promise.resolve()
  }
  if (owner === userId && ownerToken === token) return refresh()
  stop()
  owner = userId
  ownerToken = token
  window.addEventListener('focus', focus)
  window.addEventListener('labmind:logout', stop)
  document.addEventListener('visibilitychange', focus)
  timer = setInterval(focus, 30000)
  return focus() || Promise.resolve()
}

export function useNotifications() {
  return {
    recent: readonly(recent),
    unreadCount: readonly(unreadCount),
    maxId: readonly(maxId),
    loading: readonly(loading),
    stale: readonly(stale),
    revision: readonly(revision),
    refresh,
    read,
    readAll,
    start,
    stop
  }
}
