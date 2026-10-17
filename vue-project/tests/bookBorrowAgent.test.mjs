import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'
import * as library from '../src/utils/library.js'

async function panel(overrides = {}) {
  let unmount
  const saved = new Map()
  const context = vm.createContext({
    defineProps: () => ({ managed: overrides.managed || null }),
    crypto: { randomUUID: () => 'new-run' },
    sessionStorage: {
      getItem: (k) => saved.get(k),
      setItem: (k, v) => saved.set(k, v),
      removeItem: (k) => saved.delete(k)
    }
  })
  const api = {
    startBorrowRun: async () => ({
      run_id: 'new-run',
      status: 'select_book',
      books: [{ id: 1, is_active: true, available_copies: 1 }]
    }),
    selectBorrowBook: async () => ({
      run_id: 'new-run',
      status: 'confirm_borrow',
      action: { id: 'action' }
    }),
    selectReturnLoan: async () => ({
      status: 'confirm_return',
      task_type: 'return',
      action: { id: 'return-action' }
    }),
    getLoanPage: async () => ({
      status: 'select_loan',
      task_type: 'return',
      loans: [],
      loan_page: { page: 2, page_size: 6, total: 7 }
    }),
    decideBorrow: async () => ({ run_id: 'new-run', status: 'pending', receipt: { loan_id: 1 } }),
    getBorrowRun: async () => ({ run_id: 'new-run', status: 'pending' }),
    retryBorrowRun: async () => ({ run_id: 'new-run', status: 'pending' }),
    ...overrides
  }
  const dependencies = {
    vue: {
      watch: () => {},
      ref: (value) => ({ value }),
      onMounted: () => {},
      onUnmounted: (fn) => {
        unmount = fn
      }
    },
    '@/api/agentApi': api,
    '@/utils/library': library,
    '@/api/knowledgeApi': {
      getKnowledgeSourceApi:
        overrides.getKnowledgeSourceApi || (async () => ({ text: '元数据原文' }))
    },
    '@/auth': { getUserInfo: () => ({ id: 5 }) }
  }
  const source = await readFile(
    new URL('../src/components/BookBorrowAgent.vue', import.meta.url),
    'utf8'
  )
  const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1]
  const module = new vm.SourceTextModule(
    script +
      '\nexport { query, run, busy, error, search, select, decide, refresh, restart, openSource, sourceContent, sourceError, taskType, selectLoan, changeLoanPage }',
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
  return { state: module.namespace, unmount: () => unmount() }
}

test('managed book selection delegates through parent and read-only results cannot prepare', async () => {
  const calls = []
  const managed = {
    run: { run_id: 'child', status: 'select_book', books: [{ id: 1, is_active: true, available_copies: 1 }] },
    operate: async (kind, payload) => { calls.push([kind, payload.book_id]); return { status: 'confirm_borrow', action: { id: 'a' } } }
  }
  const { state } = await panel({ managed })
  await state.select(1)
  assert.deepEqual(calls, [['select', 1]])
  const readOnly = await panel({ managed: { ...managed, readOnly: true } })
  await readOnly.state.select(1)
  assert.equal(calls.length, 1)
})

test('selecting a book only prepares a confirmation; double confirmation is blocked', async () => {
  let writes = 0
  let resolve
  const { state } = await panel({
    decideBorrow: () => {
      writes++
      return new Promise((done) => {
        resolve = done
      })
    }
  })
  state.query.value = '找 Python 书'
  await state.search()
  await state.select(1)
  assert.equal(writes, 0)
  const pending = state.decide(true)
  await state.decide(true)
  assert.equal(writes, 1)
  resolve({ run_id: 'new-run', status: 'pending' })
  await pending
  assert.equal(state.run.value.status, 'pending')
})

test('network failure never fabricates success and refresh can recover receipt', async () => {
  const { state } = await panel({
    selectReturnLoan: async () => ({
      status: 'confirm_return',
      task_type: 'return',
      action: { id: 'return-action' }
    }),
    getLoanPage: async () => ({
      status: 'select_loan',
      task_type: 'return',
      loans: [],
      loan_page: { page: 2, page_size: 6, total: 7 }
    }),
    decideBorrow: async () => {
      throw Error('network')
    }
  })
  state.query.value = 'Python'
  await state.search()
  await state.select(1)
  await state.decide(true)
  assert.notEqual(state.run.value.status, 'pending')
  assert.ok(state.error.value)
  await state.refresh()
  assert.equal(state.run.value.status, 'pending')
})

test('leaving page ignores late response and empty searches make no request', async () => {
  let resolve
  let calls = 0
  const { state, unmount } = await panel({
    startBorrowRun: () => {
      calls++
      return new Promise((done) => {
        resolve = done
      })
    }
  })
  await state.search()
  assert.equal(calls, 0)
  state.query.value = 'Python'
  const pending = state.search()
  unmount()
  resolve({ status: 'select_book' })
  await pending
  assert.equal(state.run.value, null)
})

test('no stock books remain visible but cannot be selected; refresh restores evidence', async () => {
  let selected = 0
  const book = {
    id: 7,
    is_active: true,
    total_copies: 0,
    available_copies: 0,
    match_reasons: ['分类：历史图书'],
    sources: [{ chunk_id: 9 }]
  }
  const { state } = await panel({
    startBorrowRun: async () => ({ status: 'select_book', books: [book] }),
    selectBorrowBook: async () => {
      selected++
      return {}
    },
    getBorrowRun: async () => ({
      status: 'select_book',
      books: [book],
      degraded: ['vector_unavailable']
    })
  })
  state.query.value = '历史'
  await state.search()
  await state.select(7)
  assert.equal(selected, 0)
  await state.refresh()
  assert.equal(state.run.value.books[0].sources[0].chunk_id, 9)
  assert.equal(state.run.value.degraded[0], 'vector_unavailable')
})

test('source preview double click is bounded and disabled sources show an error', async () => {
  let calls = 0
  let reject
  const { state } = await panel({
    getKnowledgeSourceApi: () => {
      calls++
      return new Promise((_, fail) => {
        reject = fail
      })
    }
  })
  const pending = state.openSource({ chunk_id: 9 })
  await state.openSource({ chunk_id: 9 })
  assert.equal(calls, 1)
  reject(Error('来源已停用'))
  await pending
  assert.equal(state.sourceContent.value, null)
  assert.equal(state.sourceError.value, '来源已停用')
})

test('personal loan query accepts empty wording and selection only prepares a return', async () => {
  let submitted
  let writes = 0
  const { state } = await panel({
    startBorrowRun: async (data) => {
      submitted = data
      return {
        status: 'select_loan',
        task_type: 'my_loans',
        loans: [
          { id: 2, status: 'borrowed' },
          { id: 3, status: 'return_pending' }
        ]
      }
    },
    decideBorrow: async () => {
      writes++
      return { status: 'return_pending' }
    }
  })
  state.taskType.value = 'my_loans'
  await state.search()
  assert.equal(submitted.task_type, 'my_loans')
  assert.ok(submitted.query)
  await state.selectLoan(3)
  assert.equal(state.run.value.status, 'select_loan')
  await state.selectLoan(2)
  assert.equal(state.run.value.status, 'confirm_return')
  assert.equal(writes, 0)
  await state.decide(true)
  assert.equal(writes, 1)
  assert.equal(state.run.value.status, 'return_pending')
})

test('return task refresh restores task type and cancel on restart never confirms', async () => {
  const decisions = []
  const { state } = await panel({
    getBorrowRun: async () => ({
      status: 'confirm_return',
      task_type: 'return',
      action: { id: 'return-action' }
    }),
    decideBorrow: async (_, decision) => {
      decisions.push(decision.confirmed)
      return { status: 'cancelled' }
    }
  })
  state.query.value = '找书'
  await state.search()
  await state.refresh()
  assert.equal(state.taskType.value, 'return')
  await state.restart()
  assert.deepEqual(decisions, [false])
  assert.equal(state.run.value, null)
})

test('double return selection and pagination are blocked while a request is pending', async () => {
  let finish
  let calls = 0
  const { state } = await panel({
    selectReturnLoan: () => {
      calls++
      return new Promise((resolve) => {
        finish = resolve
      })
    }
  })
  state.run.value = { status: 'select_loan', loans: [{ id: 2, status: 'borrowed' }] }
  const pending = state.selectLoan(2)
  await state.selectLoan(2)
  await state.changeLoanPage(2)
  assert.equal(calls, 1)
  finish({ status: 'confirm_return', action: { id: 'return-action' } })
  await pending
})
