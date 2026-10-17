import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'
import * as utilities from '../src/utils/spaceReservation.js'

async function panel(overrides = {}) {
  let unmount
  const saved = new Map()
  const context = vm.createContext({
    crypto: { randomUUID: () => 'workflow-id' },
    sessionStorage: { getItem: (k) => saved.get(k), setItem: (k, v) => saved.set(k, v), removeItem: (k) => saved.delete(k) }
  })
  const dependencies = {
    vue: { ref: (value) => ({ value }), onMounted: () => {}, onUnmounted: (fn) => { unmount = fn } },
    '@/auth': { getUserInfo: () => ({ id: 5 }) },
    '@/utils/spaceReservation': utilities,
    '@/components/BookBorrowAgent.vue': { default: {} },
    '@/components/SpaceReservationAgent.vue': { default: {} },
    '@/api/workflowApi': {
      startWorkflow: async () => ({ workflow_id: 'workflow-id', status: 'ready', steps: [] }),
      getWorkflow: async () => ({ workflow_id: 'workflow-id', status: 'completed', steps: [] }),
      retryWorkflow: async () => ({ status: 'waiting', steps: [] }),
      cancelWorkflow: async () => ({ status: 'cancelled', steps: [] }),
      setWorkflowConditions: async () => ({ status: 'ready', steps: [] }),
      clarifyWorkflow: async () => ({ status: 'planning', steps: [] }),
      operateWorkflowStep: async () => ({ status: 'completed', steps: [] }),
      ...overrides
    }
  }
  const source = await readFile(new URL('../src/components/WorkflowAssistant.vue', import.meta.url), 'utf8')
  const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1]
  const module = new vm.SourceTextModule(script + '\nexport { query, run, busy, error, workflowId, form, start, refresh, advance, submitConditions, restart }', { context })
  await module.link((name) => new vm.SyntheticModule(Object.keys(dependencies[name]), function () {
    for (const [key, value] of Object.entries(dependencies[name])) this.setExport(key, value)
  }, { context }))
  await module.evaluate()
  return { state: module.namespace, unmount: () => unmount(), saved }
}

test('planning is bounded while pending and never implicitly advances or confirms', async () => {
  let calls = 0
  let resolve
  const { state } = await panel({ startWorkflow: () => { calls++; return new Promise((done) => { resolve = done }) } })
  state.query.value = '找书并预约空间'
  const first = state.start()
  await state.start()
  assert.equal(calls, 1)
  resolve({ status: 'ready', steps: [] })
  await first
  assert.equal(state.run.value.status, 'ready')
})

test('lost response retains identity and refresh restores server result', async () => {
  const { state, saved } = await panel({ startWorkflow: async () => { throw new Error('响应丢失') } })
  state.query.value = '找书'
  await state.start()
  assert.equal(state.run.value, null)
  assert.equal(saved.get('library-workflow-5'), 'workflow-id')
  await state.refresh()
  assert.equal(state.run.value.status, 'completed')
})

test('conditions must be complete before calling the server', async () => {
  let calls = 0
  const { state } = await panel({ setWorkflowConditions: async () => { calls++; return { status: 'ready', steps: [] } } })
  state.workflowId.value = 'workflow-id'
  await state.submitConditions()
  assert.equal(calls, 0)
  state.form.value = { date: '2090-10-20', start: '14:00', end: '16:00', people: 3, purpose: '讨论', note: '' }
  await state.submitConditions()
  assert.equal(calls, 1)
})

test('unmount ignores late results and restart stops unfinished work first', async () => {
  let resolve
  const { state, unmount } = await panel({ startWorkflow: () => new Promise((done) => { resolve = done }) })
  state.query.value = '找书'
  const pending = state.start()
  unmount()
  resolve({ status: 'ready', steps: [] })
  await pending
  assert.equal(state.run.value, null)
  const active = await panel({ cancelWorkflow: async () => { throw new Error('停止失败') } })
  active.state.workflowId.value = 'active'
  active.state.run.value = { status: 'waiting' }
  await active.state.restart()
  assert.equal(active.state.workflowId.value, 'active')
})
