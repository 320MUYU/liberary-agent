import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'
import * as helpers from '../src/utils/knowledge.js'

async function panel(search) {
  let unmount
  const context = vm.createContext({})
  const dependencies = {
    vue: {
      ref: (value) => ({ value }),
      onUnmounted: (fn) => {
        unmount = fn
      }
    },
    '@/api/knowledgeApi': { searchKnowledgeApi: search },
    '@/utils/knowledge': helpers
  }
  const source = await readFile(
    new URL('../src/components/KnowledgeSearchPanel.vue', import.meta.url),
    'utf8'
  )
  const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1]
  const module = new vm.SourceTextModule(
    script + '\nexport { query, strategy, result, loading, error, runSearch }',
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

test('retrieval form rejects empty input and prevents duplicate requests', async () => {
  let resolve
  let calls = 0
  const { state } = await panel(() => {
    calls++
    return new Promise((done) => {
      resolve = done
    })
  })
  await state.runSearch()
  assert.equal(calls, 0)
  state.query.value = 'R-204'
  const pending = state.runSearch()
  await state.runSearch()
  assert.equal(calls, 1)
  resolve({ candidates: [], results: [], rerank_status: 'disabled' })
  await pending
  assert.equal(state.loading.value, false)
  assert.deepEqual(state.result.value.results, [])
})

test('failed search can retry and unmounted page ignores delayed results', async () => {
  let resolve
  let fail = true
  const { state, unmount } = await panel(() =>
    fail
      ? Promise.reject(new Error('failed'))
      : new Promise((done) => {
          resolve = done
        })
  )
  state.query.value = '借阅规则'
  await state.runSearch()
  assert.ok(state.error.value)
  assert.equal(state.loading.value, false)
  fail = false
  const pending = state.runSearch()
  unmount()
  resolve({ results: [{ title: 'stale' }] })
  await pending
  assert.equal(state.result.value, null)
})
