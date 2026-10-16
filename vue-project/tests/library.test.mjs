import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'
import * as library from '../src/utils/library.js'

import {
  canRequestLoan,
  copyAvailability,
  loanActions,
  toBookPayload
} from '../src/utils/library.js'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((success, failure) => {
    resolve = success
    reject = failure
  })
  return { promise, resolve, reject }
}

async function loadView(filename, apiOverrides, exportedNames) {
  const context = vm.createContext({})
  const noOp = () => {}
  const imports = {
    vue: {
      ref: (value) => ({ value }),
      reactive: (value) => value,
      computed: (getter) => ({
        get value() {
          return getter()
        }
      }),
      onMounted: noOp
    },
    'element-plus': {
      ElMessage: { success: noOp, warning: noOp },
      ElMessageBox: { confirm: () => Promise.resolve() }
    },
    '@/bookApi.js': {
      createBookApi: noOp,
      createBookCopyApi: noOp,
      updateBookApi: noOp,
      updateBookCopyApi: noOp,
      getBookApi: noOp,
      getBookCopiesApi: noOp,
      getBooksApi: noOp,
      getAdminBooksApi: () => Promise.resolve({ items: [], total: 0 })
    },
    '@/loanApi.js': { createLoanApi: noOp },
    '@/utils/library.js': library
  }
  for (const [name, overrides] of Object.entries(apiOverrides))
    Object.assign(imports[name], overrides)
  const source = await readFile(new URL(`../src/views/${filename}`, import.meta.url), 'utf8')
  const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1]
  const view = new vm.SourceTextModule(`${script}\nexport { ${exportedNames.join(', ')} }`, {
    context
  })
  await view.link((specifier) => {
    const values = imports[specifier]
    assert.ok(values, `unexpected import: ${specifier}`)
    return new vm.SyntheticModule(
      Object.keys(values),
      function () {
        for (const [name, value] of Object.entries(values)) this.setExport(name, value)
      },
      { context }
    )
  })
  await view.evaluate()
  return view.namespace
}

test('book search resets pagination and an old response cannot replace newer results', async () => {
  const first = deferred()
  const second = deferred()
  const queries = []
  const view = await loadView(
    'BooksView.vue',
    {
      '@/bookApi.js': {
        getBooksApi: (params) => {
          queries.push(params)
          return queries.length === 1 ? first.promise : second.promise
        }
      }
    },
    ['books', 'page', 'filters', 'searchBooks', 'fetchBooks']
  )
  view.page.value = 4
  const initial = view.fetchBooks()
  view.filters.keyword = ' 新书 '
  view.searchBooks()
  second.resolve({ items: [{ id: 2, title: '新书' }], total: 1 })
  await new Promise((resolve) => setImmediate(resolve))
  first.resolve({ items: [{ id: 1, title: '过期结果' }], total: 1 })
  await initial
  assert.equal(view.books.value[0].title, '新书')
  assert.equal(queries[1].page, 1)
  assert.equal(queries[1].keyword, '新书')
})

test('rapidly saving a book twice while validation is pending creates only one book', async () => {
  const validation = deferred()
  let creates = 0
  const view = await loadView(
    'admin/BookManageView.vue',
    {
      '@/bookApi.js': {
        createBookApi: () => {
          creates += 1
          return Promise.resolve()
        }
      }
    },
    ['bookFormRef', 'saveBook']
  )
  view.bookFormRef.value = { validate: () => validation.promise }
  const first = view.saveBook()
  const second = view.saveBook()
  validation.resolve(true)
  await Promise.all([first, second])
  assert.equal(creates, 1)
})

test('rapidly saving a copy twice while validation is pending creates only one copy', async () => {
  const validation = deferred()
  let creates = 0
  const view = await loadView(
    'admin/BookManageView.vue',
    {
      '@/bookApi.js': {
        createBookCopyApi: () => {
          creates += 1
          return Promise.resolve()
        },
        getBookCopiesApi: () => Promise.resolve({ items: [], total: 0 })
      }
    },
    ['copyFormRef', 'copyBook', 'saveCopy']
  )
  view.copyBook.value = { id: 2 }
  view.copyFormRef.value = { validate: () => validation.promise }
  const first = view.saveCopy()
  const second = view.saveCopy()
  validation.resolve(true)
  await Promise.all([first, second])
  assert.equal(creates, 1)
})

test('borrowing requests require an active book and an available copy', () => {
  assert.equal(canRequestLoan({ is_active: true, available_copies: 1 }), true)
  assert.equal(canRequestLoan({ is_active: true, available_copies: 0 }), false)
  assert.equal(canRequestLoan({ is_active: false, available_copies: 2 }), false)
  assert.equal(canRequestLoan(null), false)
})

test('public catalogue entries distinguish missing holdings from unavailable copies', () => {
  assert.equal(
    library.bookAvailability({ total_copies: 0, available_copies: 0 }),
    '本馆尚未登记馆藏'
  )
  assert.equal(library.bookAvailability({ total_copies: 2, available_copies: 0 }), '暂无可借副本')
  assert.equal(library.bookAvailability({ total_copies: 2, available_copies: 1 }), '可借 1 册')
  assert.equal(library.bookLanguages({ languages: ['chi', 'eng'] }), '中文 / 英语')
  assert.equal(library.bookLanguages(null), '未提供')
  assert.equal(library.bookLanguages({ languages: ['xyz'] }), 'xyz')
})

test('reader and administrator actions follow the complete borrowing lifecycle', () => {
  assert.deepEqual(loanActions('pending', 'reader'), ['cancel'])
  assert.deepEqual(loanActions('pending', 'admin'), ['confirm-borrow', 'reject'])
  assert.deepEqual(loanActions('borrowed', 'reader'), ['request-return'])
  assert.deepEqual(loanActions('borrowed', 'admin'), [])
  assert.deepEqual(loanActions('return_pending', 'reader'), [])
  assert.deepEqual(loanActions('return_pending', 'admin'), ['confirm-return'])
  for (const status of ['returned', 'cancelled', 'rejected', 'unknown']) {
    assert.deepEqual(loanActions(status, 'reader'), [])
    assert.deepEqual(loanActions(status, 'admin'), [])
  }
  assert.deepEqual(loanActions('pending', 'unknown'), [])
})

test('copy presentation distinguishes occupied copies from maintenance and withdrawal', () => {
  assert.equal(copyAvailability({ status: 'available', is_on_loan: false }).label, '可借出')
  assert.equal(copyAvailability({ status: 'available', is_on_loan: true }).label, '借出中')
  assert.equal(copyAvailability({ status: 'maintenance', is_on_loan: false }).label, '维护中')
  assert.equal(copyAvailability({ status: 'withdrawn', is_on_loan: false }).label, '已退藏')
  assert.equal(copyAvailability({ status: 'unknown', is_on_loan: false }).label, '状态未知')
})

test('editing a book sends only editable fields and preserves false and optional empty values', () => {
  const payload = toBookPayload({
    id: 9,
    title: ' 馆藏 ',
    author: ' 作者 ',
    category: ' 小说 ',
    is_active: false,
    isbn: '',
    publisher: ' ',
    publication_year: undefined,
    description: ' 简介 ',
    cover: '',
    available_copies: 4,
    total_copies: 6
  })
  assert.deepEqual(payload, {
    title: '馆藏',
    author: '作者',
    category: '小说',
    is_active: false,
    isbn: null,
    publisher: null,
    publication_year: null,
    description: '简介',
    cover: null
  })
})

async function loadApi(filename) {
  const calls = []
  const context = vm.createContext({})
  const requestModule = new vm.SyntheticModule(
    ['default'],
    function () {
      this.setExport('default', (config) => {
        calls.push(config)
        return Promise.resolve({})
      })
    },
    { context }
  )
  const code = await readFile(new URL(`../src/${filename}`, import.meta.url), 'utf8')
  const apiModule = new vm.SourceTextModule(code, { context })
  await apiModule.link((specifier) => {
    assert.equal(specifier, './request.js')
    return requestModule
  })
  await apiModule.evaluate()
  return { api: apiModule.namespace, calls }
}

test('book API shares authenticated requests and keeps pagination and inactive filters', async () => {
  const { api, calls } = await loadApi('bookApi.js')
  const params = { page: 2, page_size: 12, keyword: '编程', category: '计算机', is_active: false }
  await api.getBooksApi(params)
  await api.getBookApi(7)
  await api.getAdminBooksApi(params)
  await api.createBookApi({ title: '编程' })
  await api.updateBookApi(7, { title: '新版' })
  await api.getBookCopiesApi(7, { page: 3, page_size: 10 })
  await api.createBookCopyApi({ book_id: 7, barcode: 'B-1', location: 'A' })
  await api.updateBookCopyApi(8, { barcode: 'B-2', location: 'B', status: 'maintenance' })
  assert.deepEqual(
    calls.map((call) => call.method),
    ['get', 'get', 'get', 'post', 'put', 'get', 'post', 'put']
  )
  assert.deepEqual(
    calls.map((call) => call.url),
    [
      '/api/books',
      '/api/books/7',
      '/api/admin/books',
      '/api/admin/books',
      '/api/admin/books/7',
      '/api/admin/books/7/copies',
      '/api/admin/book-copies',
      '/api/admin/book-copies/8'
    ]
  )
  assert.equal(calls[0].params, params)
  assert.equal(calls[2].params.is_active, false)
  assert.equal(calls[5].params.page, 3)
  assert.equal(calls[6].data.book_id, 7)
  assert.equal(calls[7].data.status, 'maintenance')
})

test('loan API maps reader and administrator transitions without leaking them across URLs', async () => {
  const { api, calls } = await loadApi('loanApi.js')
  await api.createLoanApi(4)
  await api.getMyLoansApi({ page: 2, page_size: 10, status: 'borrowed' })
  await api.cancelLoanApi(6)
  await api.requestLoanReturnApi(6)
  await api.getAdminLoansApi({ page: 1, page_size: 10, keyword: '张', status: 'pending' })
  await api.confirmBorrowApi(6)
  await api.confirmBorrowApi(7, 11)
  await api.rejectLoanApi(8, ' 已联系读者 ')
  await api.confirmReturnApi(6)
  assert.deepEqual(
    calls.map((call) => call.method),
    ['post', 'get', 'post', 'post', 'get', 'post', 'post', 'post', 'post']
  )
  assert.deepEqual(
    calls.map((call) => call.url),
    [
      '/api/loans',
      '/api/loans',
      '/api/loans/6/cancel',
      '/api/loans/6/request-return',
      '/api/admin/loans',
      '/api/admin/loans/6/confirm-borrow',
      '/api/admin/loans/7/confirm-borrow',
      '/api/admin/loans/8/reject',
      '/api/admin/loans/6/confirm-return'
    ]
  )
  assert.equal(calls[0].data.book_id, 4)
  assert.equal(calls[1].params.status, 'borrowed')
  assert.equal(calls[4].params.keyword, '张')
  assert.equal(Object.keys(calls[5].data).length, 0)
  assert.equal(calls[6].data.copy_id, 11)
  assert.equal(calls[7].data.reason, '已联系读者')
  assert.equal(calls[8].data, undefined)
})
