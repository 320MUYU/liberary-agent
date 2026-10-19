import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'
import * as Vue from 'vue'
import * as library from '../src/utils/library.js'

async function view(name, options = {}) {
  let mount, unmount, changed
  const route = { query: options.query || {} }
  const warnings = [],
    destinations = [],
    bulk = []
  const bookings = Vue.reactive([{ id: 77, status: 'rejected', reviewNote: '最新审核' }])
  const dependencies = {
    vue: {
      ref: Vue.ref,
      computed: Vue.computed,
      onMounted: (fn) => {
        mount = fn
      },
      onUnmounted: (fn) => {
        unmount = fn
      },
      watch: (_source, fn) => {
        changed = fn
      }
    },
    'vue-router': {
      useRoute: () => route,
      useRouter: () => ({ push: (to) => destinations.push(to) })
    },
    '@/auth': { getToken: () => 'token7', getUserInfo: () => ({ id: 7 }) },
    'element-plus': {
      ElMessage: { warning: (message) => warnings.push(message), success() {} },
      ElMessageBox: {}
    },
    '@/utils/library.js': library,
    '@/loanApi.js': {
      getMyLoanApi: options.loan || (async (id) => ({ id, status: 'returned' })),
      getMyLoansApi: async () => ({ items: [], total: 20 }),
      cancelLoanApi() {},
      requestLoanReturnApi() {}
    },
    '@/components/BookingDialog.vue': { default: {} },
    '@/store/labStore': {
      bookings,
      loadBookings: async () => {},
      cancelBooking() {},
      statusMap: {}
    },
    '@/notificationApi': {
      getNotificationsApi:
        options.list ||
        (async () => ({ items: [{ id: 3 }], total: 1, unread_count: 1, max_id: 3 })),
      notificationTarget: (item) => ({ path: '/loans', query: { loan_id: item.resource_id } })
    },
    '@/store/notificationStore': {
      useNotifications: () => ({
        revision: Vue.ref(0),
        read: async () => true,
        readAll: async (id) => {
          bulk.push(id)
          return true
        }
      })
    }
  }
  const context = vm.createContext({})
  const source = (
    await readFile(new URL(`../src/views/${name}View.vue`, import.meta.url), 'utf8')
  ).match(/<script setup>([\s\S]*?)<\/script>/)[1]
  const names =
    name === 'Loans'
      ? 'detail, detailVisible, openLinkedLoan'
      : name === 'Reservations'
        ? 'detail, openLinkedReservation'
        : 'items, page, maxId, markAll, fetchPage'
  const module = new vm.SourceTextModule(source + `\nexport { ${names} }`, { context })
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
    state: module.namespace,
    route,
    warnings,
    destinations,
    bulk,
    bookings,
    mount: () => mount(),
    unmount: () => unmount(),
    change: () => changed()
  }
}

test('loan notification opens current owned record outside page one and same-page query changes', async () => {
  const { state, route, change } = await view('Loans', { query: { loan_id: '77' } })
  await state.openLinkedLoan()
  assert.equal(state.detail.value.id, 77)
  assert.equal(state.detail.value.status, 'returned')
  route.query.loan_id = '88'
  await change()
  assert.equal(state.detail.value.id, 88)
})

test('late loan response cannot replace a newer detail or reopen an unmounted page', async () => {
  let finish
  const { state, route, unmount } = await view('Loans', {
    query: { loan_id: '77' },
    loan: (id) =>
      id === 77
        ? new Promise((resolve) => {
            finish = resolve
          })
        : Promise.resolve({ id })
  })
  const first = state.openLinkedLoan()
  route.query.loan_id = '88'
  await state.openLinkedLoan()
  finish({ id: 77 })
  await first
  assert.equal(state.detail.value.id, 88)
  route.query.loan_id = '77'
  const late = state.openLinkedLoan()
  unmount()
  finish({ id: 77 })
  await late
  assert.equal(state.detailVisible.value, false)
})

test('reservation notification resolves fresh owned record and missing records show a message', async () => {
  const { state, route, change, warnings } = await view('Reservations', {
    query: { reservation_id: '77' }
  })
  await state.openLinkedReservation()
  assert.equal(state.detail.value.reviewNote, '最新审核')
  route.query.reservation_id = '999'
  await change()
  assert.equal(state.detail.value, null)
  assert.equal(warnings.length, 1)
})

test('full inbox ignores stale pages and bulk read submits its displayed cutoff', async () => {
  let finish
  const { state, bulk } = await view('Notifications', {
    list: ({ page }) =>
      page === 2
        ? new Promise((resolve) => {
            finish = resolve
          })
        : Promise.resolve({ items: [{ id: 9 }], total: 1, max_id: 9, unread_count: 1 })
  })
  state.page.value = 2
  const previous = state.fetchPage()
  state.page.value = 1
  await state.fetchPage()
  finish({ items: [{ id: 3 }], total: 30, max_id: 3, unread_count: 4 })
  await previous
  assert.equal(state.items.value[0].id, 9)
  await state.markAll()
  assert.deepEqual(bulk, [9])
})
