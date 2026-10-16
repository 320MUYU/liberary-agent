import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'

async function loadRouter(token, user) {
  const context = vm.createContext({})
  const routerModule = new vm.SyntheticModule(
    ['createRouter', 'createWebHistory'],
    function () {
      this.setExport('createRouter', (config) => ({
        ...config,
        beforeEach(guard) {
          this.guard = guard
        }
      }))
      this.setExport('createWebHistory', (base) => base)
    },
    { context }
  )
  const authModule = new vm.SyntheticModule(
    ['getToken', 'getUserInfo'],
    function () {
      this.setExport('getToken', () => token)
      this.setExport('getUserInfo', () => user)
    },
    { context }
  )
  const source = await readFile(new URL('../src/router/index.js', import.meta.url), 'utf8')
  const module = new vm.SourceTextModule(source, {
    context,
    initializeImportMeta(meta) {
      meta.env = { BASE_URL: '/' }
    }
  })
  await module.link((name) => (name === 'vue-router' ? routerModule : authModule))
  await module.evaluate()
  return module.namespace.default
}

test('library routes register reader and administrator pages with login guards', async () => {
  const router = await loadRouter('', null)
  for (const path of ['/books', '/loans', '/admin/books', '/admin/loans']) {
    const route = router.routes.find((item) => item.path === path)
    assert.ok(route, `Missing ${path}`)
    assert.equal(route.meta.requiresAuth, true)
    assert.equal(typeof route.component, 'function')
    const result = router.guard({ ...route, fullPath: path })
    assert.equal(result.name, 'login')
    assert.equal(result.query.redirect, path)
  }
})

test('reader cannot open library admin pages and administrator can', async () => {
  const reader = await loadRouter('local-test-token', { role: 'student' })
  const admin = await loadRouter('local-test-token', { role: 'admin' })
  for (const path of ['/admin/books', '/admin/loans']) {
    const route = reader.routes.find((item) => item.path === path)
    assert.ok(route, `Missing ${path}`)
    assert.equal(route.meta.requiresAdmin, true)
    assert.equal(reader.guard({ ...route, fullPath: path }).path, '/')
    assert.equal(admin.guard({ ...route, fullPath: path }), undefined)
  }
  for (const path of ['/books', '/loans']) {
    const route = reader.routes.find((item) => item.path === path)
    assert.ok(route, `Missing ${path}`)
    assert.equal(reader.guard({ ...route, fullPath: path }), undefined)
  }
})
