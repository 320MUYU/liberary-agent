import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'
import * as Vue from 'vue'
import * as library from '../src/utils/library.js'

async function page(name, status, fail = false) {
  let mounted
  let watcher
  let refreshes = 0
  const requests = []
  const route = { query: { status } }
  const write = async () => {
    if (fail) throw Error('写入失败')
  }
  const list = async (query) => {
    requests.push({ ...query })
    return { items: [], total: 0 }
  }
  const imports = {
    vue: {
      ref: Vue.ref,
      computed: Vue.computed,
      reactive: Vue.reactive,
      onMounted: (fn) => {
        mounted = fn
      },
      watch: (_source, fn) => {
        watcher = fn
      }
    },
    'vue-router': { useRoute: () => route },
    'element-plus': {
      ElMessage: { success() {}, warning() {} },
      ElMessageBox: { confirm: async () => {} }
    },
    '@/store/adminTaskStore': {
      useAdminTasks: () => ({
        refresh: async () => {
          refreshes++
        }
      })
    },
    '@/adminApi': { getAdminReservationListApi: list, reviewReservationApi: write },
    '@/bookApi.js': { getBookCopiesApi: async () => ({ items: [], total: 0 }) },
    '@/loanApi.js': {
      getAdminLoansApi: list,
      confirmBorrowApi: write,
      confirmReturnApi: write,
      rejectLoanApi: write
    },
    '@/utils/library.js': library
  }
  const context = vm.createContext({})
  const source = await readFile(
    new URL(`../src/views/admin/${name}ManageView.vue`, import.meta.url),
    'utf8'
  )
  const names =
    name === 'Loan'
      ? 'filters, page, borrowTarget, rejectTarget, rejectReason, confirmBorrow, rejectLoan, confirmReturn'
      : 'query, review, openReview, submitReview'
  const module = new vm.SourceTextModule(
    source.match(/<script setup>([\s\S]*?)<\/script>/)[1] + `\nexport { ${names} }`,
    { context }
  )
  await module.link(
    (name) =>
      new vm.SyntheticModule(
        Object.keys(imports[name]),
        function () {
          for (const [key, value] of Object.entries(imports[name])) this.setExport(key, value)
        },
        { context }
      )
  )
  await module.evaluate()
  await mounted()
  return {
    state: module.namespace,
    requests,
    refreshes: () => refreshes,
    changeStatus: async (value) => {
      route.query.status = value
      await watcher(value)
    }
  }
}

test('loan notifications filter initial and same-page destinations and reset pagination', async () => {
  const view = await page('Loan', 'pending')
  assert.equal(view.requests.at(-1).status, 'pending')
  view.state.page.value = 3
  view.state.filters.keyword = '旧搜索'
  await view.changeStatus('return_pending')
  assert.equal(view.requests.at(-1).status, 'return_pending')
  assert.equal(view.requests.at(-1).page, 1)
  assert.equal(view.requests.at(-1).keyword, '')
  await view.changeStatus('invalid')
  assert.equal(view.requests.at(-1).status, undefined)
})

test('reservation notification switches from completed search back to pending', async () => {
  const view = await page('Reservation', 'approved')
  assert.equal(view.requests.at(-1).status, 'approved')
  view.state.query.page = 4
  view.state.query.keyword = '旧搜索'
  await view.changeStatus('pending')
  assert.equal(view.requests.at(-1).status, 'pending')
  assert.equal(view.requests.at(-1).page, 1)
  assert.equal(view.state.query.keyword, '')
})

test('successful borrow, reject and return actions refresh counts but failed writes do not', async () => {
  for (const fail of [false, true]) {
    const view = await page('Loan', 'pending', fail)
    view.state.borrowTarget.value = { id: 1 }
    await view.state.confirmBorrow()
    view.state.rejectTarget.value = { id: 2 }
    view.state.rejectReason.value = '测试拒绝'
    await view.state.rejectLoan()
    await view.state.confirmReturn({ id: 3, status: 'return_pending' })
    assert.equal(view.refreshes(), fail ? 0 : 3)
  }
})

test('reservation approval refreshes counts only after a successful write', async () => {
  for (const fail of [false, true]) {
    const view = await page('Reservation', 'pending', fail)
    view.state.openReview({ id: 1 }, 'approved')
    await view.state.submitReview()
    assert.equal(view.refreshes(), fail ? 0 : 1)
  }
})
