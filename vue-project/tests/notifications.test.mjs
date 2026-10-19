import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'
import * as Vue from 'vue'

async function setup(overrides = {}) {
  let identity = { id: 7, role: 'student' }
  let token = 'token7'
  let timer
  const listeners = new Map()
  const calls = []
  const snapshot = { items: [{ id: 3, read_at: null }], total: 1, unread_count: 1, max_id: 3 }
  const dependencies = {
    vue: { ref: Vue.ref, readonly: Vue.readonly },
    '@/auth': { getToken: () => token, getUserInfo: () => identity },
    '@/notificationApi': {
      getNotificationsApi: async () => snapshot,
      readNotificationApi: async (id) => calls.push(['read', id]),
      readAllNotificationsApi: async (id) => calls.push(['all', id]),
      ...overrides
    }
  }
  const document = {
    visibilityState: 'visible',
    addEventListener: (key, fn) => listeners.set(key, fn),
    removeEventListener: (key) => listeners.delete(key)
  }
  const context = vm.createContext({
    document,
    window: document,
    setInterval: (fn) => {
      timer = fn
      return 1
    },
    clearInterval: () => {
      timer = null
    }
  })
  const module = new vm.SourceTextModule(
    await readFile(new URL('../src/store/notificationStore.js', import.meta.url), 'utf8'),
    { context }
  )
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
    state: module.namespace.useNotifications(),
    snapshot,
    calls,
    document,
    listeners,
    poll: () => timer?.(),
    identity: (user, nextToken) => {
      identity = user
      token = nextToken
    }
  }
}

test('real unread counts and bounded bulk read use the displayed snapshot', async () => {
  const { state, calls } = await setup()
  await state.start(7)
  assert.equal(state.unreadCount.value, 1)
  assert.equal(state.recent.value[0].id, 3)
  await state.readAll(3)
  assert.deepEqual(calls, [['all', 3]])
})

test('failed read leaves unread state intact and is retryable', async () => {
  let fail = true
  const { state } = await setup({
    readNotificationApi: async () => {
      if (fail) throw Error('离线')
    }
  })
  await state.start(7)
  await assert.rejects(state.read(3), /离线/)
  assert.equal(state.unreadCount.value, 1)
  assert.equal(state.recent.value[0].read_at, null)
  fail = false
  await state.read(3)
})

test('logout and account change discard late responses and clear timers', async () => {
  let finish
  const { state, identity, listeners } = await setup({
    getNotificationsApi: () =>
      new Promise((resolve) => {
        finish = resolve
      })
  })
  const pending = state.start(7)
  await Promise.resolve()
  identity({ id: 8, role: 'student' }, 'token8')
  state.stop()
  finish({ items: [{ id: 99 }], unread_count: 9, max_id: 99 })
  await pending
  assert.equal(state.recent.value.length, 0)
  assert.equal(state.unreadCount.value, 0)
  assert.equal(listeners.size, 0)
})

test('polling pauses when hidden and focus refreshes stale inbox', async () => {
  let calls = 0
  const { state, document, poll, listeners } = await setup({
    getNotificationsApi: async () => {
      calls++
      if (calls === 2) throw Error('离线')
      return { items: [], unread_count: 0, max_id: 0 }
    }
  })
  await state.start(7)
  document.visibilityState = 'hidden'
  await poll()
  assert.equal(calls, 1)
  document.visibilityState = 'visible'
  await poll()
  assert.equal(state.stale.value, true)
  await listeners.get('focus')()
  assert.equal(state.stale.value, false)
})

test('read completion refreshes after an older in-flight inbox request', async () => {
  let finish
  let calls = 0
  const { state } = await setup({
    getNotificationsApi: () =>
      ++calls === 1
        ? new Promise((resolve) => {
            finish = resolve
          })
        : Promise.resolve({ items: [{ id: 3, read_at: 'now' }], unread_count: 0, max_id: 3 })
  })
  const initial = state.start(7)
  await Promise.resolve()
  const read = state.read(3)
  await Promise.resolve()
  finish({ items: [{ id: 3, read_at: null }], unread_count: 1, max_id: 3 })
  await Promise.all([initial, read])
  assert.equal(state.unreadCount.value, 0)
  assert.equal(calls, 2)
})

test('an old read operation cannot refresh or mutate another account', async () => {
  let finish
  let gets = 0
  const { state, identity } = await setup({
    readNotificationApi: () =>
      new Promise((resolve) => {
        finish = resolve
      }),
    getNotificationsApi: async () => {
      gets++
      return { items: [], unread_count: 0, max_id: 0 }
    }
  })
  await state.start(7)
  const pending = state.read(3)
  identity({ id: 8, role: 'student' }, 'token8')
  await state.start(8)
  finish()
  await pending
  assert.equal(gets, 2)
})
