import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'
import * as utilities from '../src/utils/spaceReservation.js'

const conditions = {
  date: '2090-10-20',
  start: '14:00',
  end: '16:00',
  people: 3,
  purpose: '课程讨论',
  note: ''
}
async function panel(overrides = {}, stored = '') {
  let unmount
  let mounted
  const saved = new Map(stored ? [['space-reservation-run-5', stored]] : [])
  const context = vm.createContext({
    crypto: { randomUUID: () => 'new-space' },
    sessionStorage: {
      getItem: (key) => saved.get(key),
      setItem: (key, value) => saved.set(key, value),
      removeItem: (key) => saved.delete(key)
    }
  })
  const dependencies = {
    vue: {
      ref: (value) => ({ value }),
      onMounted: (fn) => {
        mounted = fn
      },
      onUnmounted: (fn) => {
        unmount = fn
      }
    },
    '@/auth': { getUserInfo: () => ({ id: 5 }) },
    '@/utils/spaceReservation': utilities,
    '@/api/agentApi': {
      startBorrowRun: async () => ({
        status: 'select_space',
        conditions,
        spaces: [
          { id: 1, can_reserve: true },
          { id: 2, can_reserve: false }
        ]
      }),
      getBorrowRun: async () => ({
        status: 'confirm_reservation',
        conditions,
        action: { id: 'action', conditions }
      }),
      selectReservationSpace: async () => ({
        status: 'confirm_reservation',
        conditions,
        action: { id: 'action', conditions }
      }),
      getSpacePage: async () => ({ status: 'select_space', conditions, spaces: [], page: 2 }),
      decideBorrow: async (_, data) => ({
        status: data.confirmed ? 'reservation_pending' : 'cancelled'
      }),
      retryBorrowRun: async () => ({ status: 'reservation_pending' }),
      ...overrides
    }
  }
  const source = await readFile(
    new URL('../src/components/SpaceReservationAgent.vue', import.meta.url),
    'utf8'
  )
  const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1]
  const module = new vm.SourceTextModule(
    script +
      '\nexport { form, query, run, busy, error, search, selectSpace, changePage, decide, refresh, restart }',
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
  return { state: module.namespace, mount: () => mounted(), unmount: () => unmount(), saved }
}

test('incomplete conditions never start a task; complete conditions are bound in the request', async () => {
  const calls = []
  const { state } = await panel({
    startBorrowRun: async (data) => {
      calls.push(data)
      return { status: 'select_space', spaces: [] }
    }
  })
  await state.search()
  assert.equal(calls.length, 0)
  assert.ok(state.error.value)
  state.form.value = { ...conditions }
  await state.search()
  assert.equal(calls.length, 1)
  assert.equal(calls[0].task_type, 'reservation')
  assert.equal(calls[0].conditions.people, 3)
  assert.ok(calls[0].query)
})
test('unavailable spaces cannot be selected; selection does not submit a reservation', async () => {
  let writes = 0
  const { state } = await panel({
    decideBorrow: async () => {
      writes++
      return { status: 'reservation_pending' }
    }
  })
  state.form.value = { ...conditions }
  await state.search()
  await state.selectSpace(2)
  assert.equal(state.run.value.status, 'select_space')
  await state.selectSpace(1)
  assert.equal(state.run.value.status, 'confirm_reservation')
  assert.equal(writes, 0)
  await state.decide(true)
  assert.equal(writes, 1)
})
test('duplicate confirmation is bounded while the first request is pending', async () => {
  let complete
  let calls = 0
  const { state } = await panel(
    {
      decideBorrow: () => {
        calls++
        return new Promise((resolve) => {
          complete = resolve
        })
      }
    },
    'saved'
  )
  await state.refresh()
  const pending = state.decide(true)
  await state.decide(true)
  await state.changePage(2)
  assert.equal(calls, 1)
  complete({ status: 'reservation_pending' })
  await pending
})
test('mount restores the exact conditions and restart cancels only the prepared operation', async () => {
  const decisions = []
  const { state, mount, saved } = await panel(
    {
      decideBorrow: async (_, data) => {
        decisions.push(data.confirmed)
        return { status: 'cancelled' }
      }
    },
    'saved'
  )
  await mount()
  assert.equal(state.form.value.date, conditions.date)
  assert.equal(state.run.value.status, 'confirm_reservation')
  await state.restart()
  assert.deepEqual(decisions, [false])
  assert.equal(saved.size, 0)
  assert.equal(state.run.value, null)
})
test('lost confirmation response displays an error and refresh recovers the original receipt', async () => {
  let reads = 0
  const { state } = await panel(
    {
      decideBorrow: async () => {
        throw Error('连接中断')
      },
      getBorrowRun: async () =>
        ++reads === 1
          ? { status: 'confirm_reservation', action: { id: 'action' } }
          : { status: 'reservation_pending', receipt: { reservation_id: 7 } }
    },
    'saved'
  )
  await state.refresh()
  await state.decide(true)
  assert.equal(state.run.value.status, 'confirm_reservation')
  assert.match(state.error.value, /连接中断/)
  await state.refresh()
  assert.equal(state.run.value.receipt.reservation_id, 7)
})
test('results arriving after unmount cannot replace the current view', async () => {
  let finish
  const { state, unmount } = await panel(
    {
      getBorrowRun: () =>
        new Promise((resolve) => {
          finish = resolve
        })
    },
    'saved'
  )
  const pending = state.refresh()
  unmount()
  finish({ status: 'reservation_pending' })
  await pending
  assert.equal(state.run.value, null)
})
