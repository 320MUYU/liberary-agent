import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'
import * as Vue from 'vue'

const counts = {
  reservation_pending: 1,
  borrow_pending: 2,
  return_pending: 3,
  evaluation_pending: 114,
  total: 120
}
async function store(api = async () => counts) {
  const listeners = new Map()
  let timer
  let identity = { id: 7, role: 'admin' }
  const document = {
    visibilityState: 'visible',
    addEventListener: (key, fn) => listeners.set(key, fn),
    removeEventListener: (key) => listeners.delete(key)
  }
  const context = vm.createContext({
    window: {
      addEventListener: (key, fn) => listeners.set(key, fn),
      removeEventListener: (key) => listeners.delete(key)
    },
    document,
    setInterval: (fn) => {
      timer = fn
      return 1
    },
    clearInterval: () => {
      timer = null
    }
  })
  const dependencies = {
    vue: { ref: Vue.ref, computed: Vue.computed },
    '@/adminApi': { getAdminTaskSummaryApi: api },
    '@/auth': { getToken: () => (identity ? 'token' : null), getUserInfo: () => identity }
  }
  const source = await readFile(new URL('../src/store/adminTaskStore.js', import.meta.url), 'utf8')
  const module = new vm.SourceTextModule(source, { context })
  await module.link(
    (name) =>
      new vm.SyntheticModule(
        Object.keys(dependencies[name]),
        function () {
          for (const [key, value] of Object.entries(dependencies[name])) this.setExport(key, value)
        },
        { context }
      )
  )
  await module.evaluate()
  return {
    state: module.namespace.useAdminTasks(),
    listeners,
    document,
    poll: () => timer?.(),
    setIdentity: (value) => {
      identity = value
    }
  }
}

test('admin badges separate approvals from AI reviews and link to actionable filters', async () => {
  const { state } = await store()
  await state.start(7)
  assert.equal(state.countFor('/admin/reservations'), 1)
  assert.equal(state.countFor('/admin/loans'), 5)
  assert.equal(state.countFor('/admin/evaluation-reviews'), 114)
  assert.equal(state.items.value.length, 4)
  assert.equal(
    state.items.value.find((item) => item.key === 'return_pending').to.query.status,
    'return_pending'
  )
  assert.equal(
    state.items.value.find((item) => item.key === 'evaluation_pending').to.query.status,
    'pending'
  )
})

test('overlapping refreshes are deduplicated and logout discards late data', async () => {
  let finish
  let calls = 0
  const { state, setIdentity } = await store(() => {
    calls++
    return new Promise((resolve) => {
      finish = resolve
    })
  })
  const pending = state.start(7)
  const other = state.refresh()
  await Promise.resolve()
  assert.equal(calls, 1)
  setIdentity(null)
  state.stop()
  finish(counts)
  await Promise.all([pending, other])
  assert.equal(state.summary.value, null)
  assert.equal(state.items.value.length, 0)
})

test('a synchronous request failure can recover on the next refresh', async () => {
  let fail = true
  const { state } = await store(() => {
    if (fail) throw Error('request setup failed')
    return Promise.resolve(counts)
  })
  await state.start(7)
  assert.equal(state.loading.value, false)
  assert.equal(state.stale.value, true)
  fail = false
  await state.refresh()
  assert.equal(state.summary.value.total, 120)
  assert.equal(state.stale.value, false)
})

test('a completed write refetches after an older in-flight count request', async () => {
  let finish
  let calls = 0
  const { state } = await store(() => {
    calls++
    return calls === 1
      ? new Promise((resolve) => {
          finish = resolve
        })
      : Promise.resolve({ ...counts, total: 119, reservation_pending: 0 })
  })
  const initial = state.start(7)
  await Promise.resolve()
  const afterWrite = state.refresh({ afterWrite: true })
  finish(counts)
  await Promise.all([initial, afterWrite])
  assert.equal(calls, 2)
  assert.equal(state.summary.value.reservation_pending, 0)
})

test('polling pauses in hidden tabs and failure keeps counts marked stale until explicit recovery', async () => {
  let fail = false
  let calls = 0
  const { state, document, poll, listeners } = await store(async () => {
    calls++
    if (fail) throw Error('离线')
    return counts
  })
  await state.start(7)
  document.visibilityState = 'hidden'
  await poll()
  assert.equal(calls, 1)
  document.visibilityState = 'visible'
  fail = true
  await poll()
  assert.equal(state.summary.value.total, 120)
  assert.equal(state.stale.value, true)
  await poll()
  assert.equal(calls, 2)
  fail = false
  await listeners.get('focus')()
  assert.equal(state.stale.value, false)
  assert.equal(calls, 3)
  state.stop()
  assert.equal(listeners.size, 0)
})

test('reader sessions never fetch administrator counts and zero counts clear badges', async () => {
  let calls = 0
  const { state, setIdentity } = await store(async () => {
    calls++
    return {
      reservation_pending: 0,
      borrow_pending: 0,
      return_pending: 0,
      evaluation_pending: 0,
      total: 0
    }
  })
  setIdentity({ id: 8, role: 'student' })
  await state.start(8)
  assert.equal(calls, 0)
  setIdentity({ id: 7, role: 'admin' })
  await state.start(7)
  assert.equal(state.items.value.length, 0)
  assert.equal(state.countFor('/admin/loans'), 0)
})
