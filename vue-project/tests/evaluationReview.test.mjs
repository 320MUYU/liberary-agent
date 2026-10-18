import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'
import * as utilities from '../src/utils/evaluationReview.js'

const initialReview = {
  status: 'pending_human',
  revision: 0,
  answer_correct: null,
  citations_support: null,
  notes: ''
}
const answer = (review = initialReview) => ({ id: 'q1', question: '问题', review })
const report = {
  id: 1,
  report_id: 'hash',
  metrics: { total: 2 },
  cases: [answer(), { ...answer(), id: 'q2' }]
}

async function page(overrides = {}, options = {}) {
  let mounted
  let unmounted
  let leave
  let update
  let routeWatcher
  let refreshes = 0
  const route = { query: { status: options.status } }
  const storage = new Map(
    options.position ? [['evaluation-review-position-7', JSON.stringify(options.position)]] : []
  )
  const context = vm.createContext({
    localStorage: {
      getItem: (key) => storage.get(key),
      setItem: (key, value) => storage.set(key, value)
    },
    window: {
      addEventListener() {},
      removeEventListener() {},
      confirm: () => options.confirm !== false
    },
    document: {},
    Blob,
    URL
  })
  const dependencies = {
    '@/components/AiAnswerContent.vue': { default: {} },
    '@/store/adminTaskStore': {
      useAdminTasks: () => ({
        refresh: async () => {
          refreshes++
        }
      })
    },
    vue: {
      ref: (value) => ({ value }),
      computed: (fn) => ({
        get value() {
          return fn()
        }
      }),
      onMounted: (fn) => {
        mounted = fn
      },
      onUnmounted: (fn) => {
        unmounted = fn
      },
      watch: (_source, fn) => {
        routeWatcher = fn
      }
    },
    'vue-router': {
      useRoute: () => route,
      onBeforeRouteUpdate: (fn) => {
        update = fn
      },
      onBeforeRouteLeave: (fn) => {
        leave = fn
      }
    },
    '@/auth': { getUserInfo: () => ({ id: 7 }) },
    '@/utils/evaluationReview': utilities,
    '@/api/evaluationReviewApi': {
      listEvaluationRuns: async () => [report],
      getEvaluationRun: async () => structuredClone(report),
      getEvaluationCase: async (_run, id) => ({ ...answer(), id }),
      importEvaluationReport: async () => report,
      saveEvaluationReview: async (_run, id, payload) => ({
        ...answer(),
        id,
        review: { ...payload, revision: payload.revision + 1 }
      }),
      exportEvaluationReviews: async () => ({}),
      ...overrides
    }
  }
  const source = await readFile(
    new URL('../src/views/admin/EvaluationReviewView.vue', import.meta.url),
    'utf8'
  )
  const module = new vm.SourceTextModule(
    source.match(/<script setup>([\s\S]*?)<\/script>/)[1] +
      '\nexport { runs, run, currentCase, form, busy, error, dirty, filter, visibleCases, initialize, loadRun, selectCase, save, importFile }',
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
  await mounted()
  return {
    state: module.namespace,
    storage,
    unmount: () => unmounted(),
    leave: () => leave(),
    refreshes: () => refreshes,
    changeStatus: async (status) => {
      const to = { query: { status } }
      if (update && !update(to, route)) return false
      route.query.status = status
      await routeWatcher?.(status)
      return true
    }
  }
}

test('restore persisted decisions on refresh and keep partial draft out of reviewed filter', async () => {
  const reviewed = {
    ...initialReview,
    status: 'reviewed',
    answer_correct: false,
    citations_support: true,
    revision: 2
  }
  const { state } = await page({ getEvaluationCase: async () => answer(reviewed) })
  assert.equal(state.form.value.answer_correct, false)
  assert.equal(state.currentCase.value.review.revision, 2)
  assert.equal(state.dirty.value, false)
  state.form.value.notes = '编辑'
  assert.equal(state.dirty.value, true)
  await state.loadRun(1)
  assert.equal(state.form.value.notes, '')
})

test('save failure keeps input and revision; submit requires two explicit booleans', async () => {
  let calls = 0
  const { state } = await page({
    saveEvaluationReview: async () => {
      calls++
      throw Error('版本冲突')
    }
  })
  await state.save('reviewed')
  assert.equal(calls, 0)
  state.form.value = { answer_correct: true, citations_support: false, notes: '保留输入' }
  await state.save('reviewed')
  assert.equal(state.form.value.notes, '保留输入')
  assert.equal(state.currentCase.value.review.revision, 0)
  assert.equal(state.dirty.value, true)
  assert.match(state.error.value, /版本冲突/)
})

test('duplicate save and navigation while saving do not issue extra writes or lose identity', async () => {
  let finish
  let calls = 0
  const { state } = await page({
    saveEvaluationReview: async (_run, id, payload) => {
      calls++
      return new Promise((resolve) => {
        finish = () => resolve({ ...answer(), id, review: { ...payload, revision: 1 } })
      })
    }
  })
  state.form.value.notes = '草稿'
  const pending = state.save('draft')
  await state.save('draft')
  await state.selectCase('q2')
  assert.equal(calls, 1)
  assert.equal(state.currentCase.value.id, 'q1')
  finish()
  await pending
  assert.equal(state.currentCase.value.review.revision, 1)
  assert.equal(state.dirty.value, false)
})

test('unmount ignores late responses and leaving during save is blocked', async () => {
  let finish
  const { state, unmount, leave } = await page({
    saveEvaluationReview: () =>
      new Promise((resolve) => {
        finish = resolve
      })
  })
  state.form.value.notes = '在途'
  const pending = state.save('draft')
  assert.equal(leave(), false)
  unmount()
  finish({ ...answer(), review: { ...initialReview, revision: 9 } })
  await pending
  assert.equal(state.currentCase.value.review.revision, 0)
})

test('evidence utility separates actually cited excerpts from full previews', () => {
  const rows = utilities.citedSources({
    answer: {
      content: '结论[2]',
      sources: [
        { number: 1, excerpt: '未引用' },
        { number: 2, excerpt: '实际摘录' }
      ]
    },
    previews: [{ text: '更长原文' }]
  })
  assert.deepEqual(
    rows.map((row) => row.cited),
    [false, true]
  )
  assert.equal(rows[1].excerpt, '实际摘录')
  assert.equal(utilities.percent(null), '待审核')
  assert.equal(utilities.percent(0.5), '50%')
})

test('filters distinguish automatic failure and human negative judgments', () => {
  const rows = [
    { contract_pass: false, review: { status: 'draft', answer_correct: false } },
    {
      contract_pass: true,
      review: { status: 'reviewed', answer_correct: true, citations_support: false }
    }
  ]
  assert.deepEqual(utilities.filterCases(rows, 'pending'), [rows[0]])
  assert.deepEqual(utilities.filterCases(rows, 'human_negative'), [rows[1]])
  assert.deepEqual(utilities.filterCases(rows, 'automatic_failure'), [rows[0]])
})

test('pending cases never inherit an automatic success as a human judgment', async () => {
  const { state, storage } = await page()
  assert.equal(state.form.value.answer_correct, null)
  assert.equal(state.form.value.citations_support, null)
  assert.equal(JSON.parse(storage.get('evaluation-review-position-7')).caseId, 'q1')
  await state.selectCase('q2')
  assert.equal(JSON.parse(storage.get('evaluation-review-position-7')).caseId, 'q2')
})

test('failed case loading preserves old case and its unsaved judgment', async () => {
  const { state } = await page({
    getEvaluationCase: async (_run, id) => {
      if (id === 'q2') throw Error('网络异常')
      return answer()
    }
  })
  state.form.value.notes = '不能丢失'
  await state.selectCase('q2')
  assert.equal(state.currentCase.value.id, 'q1')
  assert.equal(state.form.value.notes, '不能丢失')
})

test('reimport reloads server progress and clears the input for repeated selection', async () => {
  let imports = 0
  const { state } = await page({
    importEvaluationReport: async () => {
      imports++
      return report
    }
  })
  const target = {
    files: [{ name: 'regression.json', size: 100, text: async () => '\uFEFF{"results":[]}' }],
    value: 'selected'
  }
  await state.importFile({ target })
  assert.equal(imports, 1)
  assert.equal(target.value, '')
  assert.equal(state.currentCase.value.id, 'q1')
  assert.equal(state.form.value.answer_correct, null)
})

test('only successful saves and imports refresh the shared pending count', async () => {
  const view = await page()
  await view.state.save('draft')
  assert.equal(view.refreshes(), 1)
  await view.state.importFile({
    target: { files: [{ name: 'test.json', size: 2, text: async () => '{}' }], value: 'selected' }
  })
  assert.equal(view.refreshes(), 2)
  const failed = await page({
    saveEvaluationReview: async () => {
      throw Error('保存失败')
    }
  })
  await failed.state.save('draft')
  assert.equal(failed.refreshes(), 0)
})

test('notification entry skips a remembered completed report and opens a pending answer', async () => {
  const completed = { ...report, metrics: { total: 2, human_reviewed: 2 } }
  const pending = {
    ...report,
    id: 2,
    metrics: { total: 2, human_reviewed: 1 },
    cases: [answer({ ...initialReview, status: 'reviewed' }), { ...answer(), id: 'q2' }]
  }
  const view = await page(
    {
      listEvaluationRuns: async () => [completed, pending],
      getEvaluationRun: async (id) => (id === 1 ? completed : pending)
    },
    { status: 'pending', position: { runId: 1, caseId: 'q1' } }
  )
  assert.equal(view.state.run.value.id, 2)
  assert.equal(view.state.currentCase.value.id, 'q2')
  assert.equal(view.state.filter.value, 'pending')
})

test('same-page pending notification respects unsaved input before changing selection', async () => {
  const view = await page({}, { confirm: false })
  view.state.form.value.notes = '保留未保存的判断'
  assert.equal(await view.changeStatus('pending'), false)
  assert.equal(view.state.form.value.notes, '保留未保存的判断')
  assert.equal(view.state.filter.value, 'all')
  const clean = await page()
  await clean.changeStatus('pending')
  assert.equal(clean.state.filter.value, 'pending')
})
