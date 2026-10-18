import { computed, ref } from 'vue'
import { getAdminTaskSummaryApi } from '@/adminApi'
import { getToken, getUserInfo } from '@/auth'

const summary = ref(null)
const loading = ref(false)
const stale = ref(false)
let owner = null
let generation = 0
let pending = null
let timer = null

const definitions = [
  {
    key: 'reservation_pending',
    title: '预约待审核',
    unit: '条预约',
    to: { path: '/admin/reservations', query: { status: 'pending' } }
  },
  {
    key: 'borrow_pending',
    title: '借出待确认',
    unit: '条借阅申请',
    to: { path: '/admin/loans', query: { status: 'pending' } }
  },
  {
    key: 'return_pending',
    title: '归还待确认',
    unit: '条归还申请',
    to: { path: '/admin/loans', query: { status: 'return_pending' } }
  },
  {
    key: 'evaluation_pending',
    title: 'AI 回答待审核',
    unit: '条回答',
    to: { path: '/admin/evaluation-reviews', query: { status: 'pending' } }
  }
]
const items = computed(() =>
  definitions
    .map((item) => ({ ...item, count: summary.value?.[item.key] || 0 }))
    .filter((item) => item.count > 0)
)

function authorized(userId = owner) {
  const user = getUserInfo()
  return !!getToken() && user?.role === 'admin' && user.id === userId
}

function refresh({ afterWrite = false } = {}) {
  if (!owner || !authorized()) return Promise.resolve()
  if (pending && afterWrite) {
    const current = generation
    return pending.then(() => (current === generation ? refresh() : undefined))
  }
  if (pending) return pending
  const current = generation
  loading.value = true
  const request = Promise.resolve().then(async () => {
    try {
      const data = await getAdminTaskSummaryApi()
      if (current === generation && authorized()) {
        summary.value = data
        stale.value = false
      }
    } catch {
      if (current === generation) stale.value = true
    } finally {
      if (current === generation) loading.value = false
      if (pending === request) pending = null
    }
  })
  pending = request
  return request
}

function focus() {
  if (document.visibilityState === 'visible') return refresh()
}

function stop() {
  generation++
  owner = null
  pending = null
  summary.value = null
  stale.value = false
  loading.value = false
  if (timer) clearInterval(timer)
  timer = null
  window.removeEventListener('focus', focus)
  document.removeEventListener('visibilitychange', focus)
}

function start(userId) {
  if (!authorized(userId)) {
    stop()
    return Promise.resolve()
  }
  if (owner === userId) return refresh()
  stop()
  owner = userId
  window.addEventListener('focus', focus)
  document.addEventListener('visibilitychange', focus)
  timer = setInterval(() => {
    if (!stale.value && document.visibilityState === 'visible') return refresh()
  }, 30000)
  return refresh()
}

function countFor(path) {
  const data = summary.value
  if (!data) return null
  if (path === '/admin/reservations') return data.reservation_pending
  if (path === '/admin/loans') return data.borrow_pending + data.return_pending
  if (path === '/admin/evaluation-reviews') return data.evaluation_pending
  return 0
}

export function useAdminTasks() {
  return { summary, loading, stale, items, countFor, refresh, start, stop }
}
