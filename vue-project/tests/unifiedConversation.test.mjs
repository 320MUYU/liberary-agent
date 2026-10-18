import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'

async function panel(overrides = {}, initial = {}) {
  const saved = new Map(Object.entries(initial))
  let unmount
  let counter = 0
  const context = vm.createContext({
    crypto: { randomUUID: () => `request-${++counter}` },
    sessionStorage: {
      getItem: (key) => saved.get(key) || null,
      setItem: (key, value) => saved.set(key, value),
      removeItem: (key) => saved.delete(key)
    }
  })
  const snapshot = { conversation_id: 'conversation', turns: [], tasks: [] }
  const dependencies = {
    vue: {
      ref: (value) => ({ value }),
      computed: (getter) => ({
        get value() {
          return getter()
        }
      }),
      nextTick: (fn) => fn?.(),
      onMounted: () => {},
      onUnmounted: (fn) => {
        unmount = fn
      }
    },
    '@/auth': { getUserInfo: () => ({ id: 5 }) },
    '@/components/ConversationTaskCard.vue': { default: {} },
    '@/components/AiAnswerContent.vue': { default: {} },
    '@/api/conversationApi': {
      createConversation: async () => snapshot,
      getConversation: async () => snapshot,
      sendConversationMessage: async () => snapshot,
      operateConversationTask: async () => snapshot,
      ...overrides
    }
  }
  const source = await readFile(new URL('../src/views/AssistantView.vue', import.meta.url), 'utf8')
  const module = new vm.SourceTextModule(
    source.match(/<script setup>([\s\S]*?)<\/script>/)[1] +
      '\nexport { input, hint, state, busy, error, pending, conversationId, send, retryPending, refresh, newConversation, operateTask }',
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
  return { state: module.namespace, saved, unmount: () => unmount() }
}

test('capability preference keeps the same conversation and concurrent sends are bounded', async () => {
  const messages = []
  let resolve
  const { state } = await panel({
    sendConversationMessage: async (cid, data) => {
      messages.push([cid, data])
      if (messages.length === 1)
        await new Promise((done) => {
          resolve = done
        })
      return {
        conversation_id: cid,
        turns: [{ request_id: data.request_id, text: data.text }],
        tasks: []
      }
    }
  })
  state.input.value = '查馆规'
  state.hint.value = 'knowledge'
  const first = state.send()
  await new Promise((done) => setImmediate(done))
  await state.send('再次发送')
  assert.equal(messages.length, 1)
  resolve()
  await first
  state.hint.value = 'library'
  await state.send('找书')
  assert.equal(messages[0][0], messages[1][0])
  assert.equal(messages[1][1].hint, 'library')
})

test('lost response retries the same message identity and refresh retains the draft', async () => {
  const attempts = []
  const { state, saved } = await panel({
    sendConversationMessage: async (cid, data) => {
      attempts.push(data.request_id)
      if (attempts.length === 1) throw new Error('响应丢失')
      return { conversation_id: cid, turns: [], tasks: [] }
    }
  })
  await state.send('找书')
  assert.match(state.error.value, /响应丢失/)
  assert.ok(saved.get('library-conversation-pending-5'))
  await state.refresh()
  assert.ok(state.pending.value)
  await state.retryPending()
  assert.equal(attempts[0], attempts[1])
  assert.equal(state.pending.value, null)
})

test('automatic progression stops for selection and never sends a confirmation', async () => {
  const calls = []
  const { state } = await panel({
    sendConversationMessage: async (cid, data) => ({
      conversation_id: 'conversation',
      turns: [{ request_id: data.request_id, workflow_id: 'task' }],
      tasks: [{ workflow_id: 'task', status: 'ready', steps: [] }]
    }),
    operateConversationTask: async (cid, task, operation) => {
      calls.push(operation)
      return {
        conversation_id: cid,
        turns: [],
        tasks: [{ workflow_id: task, status: 'waiting', steps: [] }]
      }
    }
  })
  await state.send('借书')
  assert.deepEqual(calls, ['retry'])
})

test('a follow-up question never advances an unrelated ready task', async () => {
  let calls = 0
  const { state } = await panel({
    sendConversationMessage: async (cid, data) => ({
      conversation_id: cid,
      turns: [{ request_id: data.request_id, reply: { content: '需要哪个任务？' } }],
      tasks: [{ workflow_id: 'earlier-task', status: 'ready' }]
    }),
    operateConversationTask: async () => {
      calls++
      throw new Error('不应推进')
    }
  })
  await state.send('需要哪个任务？')
  assert.equal(calls, 0)
})

test('unmount ignores late results and starting a new chat preserves existing tasks', async () => {
  let resolve
  const { state, unmount } = await panel({
    sendConversationMessage: () =>
      new Promise((done) => {
        resolve = done
      })
  })
  const waiting = state.send('预约空间')
  await new Promise((done) => setImmediate(done))
  unmount()
  resolve({ turns: [{ text: '迟到回答' }], tasks: [] })
  await waiting
  assert.equal(state.state.value.turns.length, 0)
  const second = await panel()
  await second.state.send('你好')
  second.state.state.value.tasks = [{ workflow_id: 'old', status: 'waiting' }]
  second.state.newConversation()
  assert.equal(second.state.conversationId.value, '')
})
