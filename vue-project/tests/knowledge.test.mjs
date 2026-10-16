import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'

import {
  canPublishVersion,
  canRetryVersion,
  latestVersion,
  safeKnowledgeError,
  shouldPollKnowledgeDocuments,
  validateKnowledgeUpload
} from '../src/utils/knowledge.js'
import { formatRetrievalScore, validateRetrievalQuery } from '../src/utils/knowledge.js'

test('retrieval query validation and missing scores remain distinct from zero', () => {
  assert.match(validateRetrievalQuery('  '), /问题/)
  assert.match(validateRetrievalQuery('x'.repeat(1001)), /1000/)
  assert.equal(validateRetrievalQuery('R-204在哪里？'), '')
  assert.equal(formatRetrievalScore(null), '—')
  assert.equal(formatRetrievalScore(0), '0.0000')
  assert.equal(formatRetrievalScore(Number.NaN), '—')
})

test('upload validation accepts supported nonempty files and trims required titles', () => {
  assert.equal(
    validateKnowledgeUpload({ title: ' 馆规 ', file: { name: 'rules.PDF', size: 30 } }),
    ''
  )
  assert.match(
    validateKnowledgeUpload({ title: ' ', file: { name: 'rules.pdf', size: 30 } }),
    /标题/
  )
  assert.match(
    validateKnowledgeUpload({ title: '馆规', file: { name: 'rules.doc', size: 30 } }),
    /格式/
  )
  assert.match(
    validateKnowledgeUpload({ title: '馆规', file: { name: 'rules.pdf', size: 0 } }),
    /空文件/
  )
  assert.match(
    validateKnowledgeUpload({
      title: '馆规',
      file: { name: 'rules.pdf', size: 10 * 1024 * 1024 + 1 }
    }),
    /10 MB/
  )
  assert.equal(
    validateKnowledgeUpload({ title: '', file: { name: 'rules.md', size: 30 } }, false),
    ''
  )
})

test('publishing only permits ready versions and can reenable a disabled active version', () => {
  const ready = { id: 2, status: 'ready' }
  assert.equal(canPublishVersion({ status: 'draft' }, ready), true)
  assert.equal(canPublishVersion({ status: 'published', active_version_id: 2 }, ready), false)
  assert.equal(canPublishVersion({ status: 'disabled', active_version_id: 2 }, ready), true)
  assert.equal(canPublishVersion({ status: 'deleted' }, ready), false)
  assert.equal(canPublishVersion({ status: 'published' }, { id: 3, status: 'indexing' }), false)
  assert.equal(canRetryVersion({ status: 'failed' }), true)
  assert.equal(canRetryVersion({ status: 'indexing' }), false)
})

test('progress polling stops when versions finish and follows latest_version_id', () => {
  const document = {
    status: 'published',
    latest_version_id: 2,
    versions: [
      { id: 2, version_number: 2, status: 'indexing' },
      { id: 1, version_number: 1, status: 'ready' }
    ]
  }
  assert.equal(latestVersion(document).id, 2)
  assert.equal(shouldPollKnowledgeDocuments([document]), true)
  document.versions[0].status = 'ready'
  assert.equal(shouldPollKnowledgeDocuments([document]), false)
  assert.equal(
    shouldPollKnowledgeDocuments([
      { ...document, status: 'deleted', versions: [{ status: 'queued' }] }
    ]),
    false
  )
})

test('failure details never expose internal file paths', () => {
  assert.equal(safeKnowledgeError('没有可提取的文本'), '没有可提取的文本')
  assert.doesNotMatch(
    safeKnowledgeError('无法解析 C:\\server\\secret\\file.pdf'),
    /server|secret|C:/
  )
  assert.doesNotMatch(safeKnowledgeError('无法解析 /tmp/private/file.pdf'), /private|tmp/)
})

test('knowledge API uses the shared authenticated request and expected lifecycle URLs', async () => {
  const calls = []
  const context = vm.createContext({ FormData, Blob })
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
  const code = await readFile(new URL('../src/api/knowledgeApi.js', import.meta.url), 'utf8')
  const apiModule = new vm.SourceTextModule(code, { context })
  await apiModule.link((specifier) => {
    assert.equal(specifier, '../request.js')
    return requestModule
  })
  await apiModule.evaluate()
  const api = apiModule.namespace
  await api.getKnowledgeDocumentsApi()
  await api.uploadKnowledgeDocumentApi({ title: ' 馆规 ', file: new Blob(['规则']) })
  await api.uploadKnowledgeVersionApi(7, { title: '', file: new Blob(['新版规则']) })
  await api.publishKnowledgeDocumentApi(7, 12)
  await api.disableKnowledgeDocumentApi(7)
  await api.retryKnowledgeVersionApi(12)
  await api.deleteKnowledgeDocumentApi(7)
  assert.deepEqual(
    calls.map((call) => call.method),
    ['get', 'post', 'post', 'post', 'post', 'post', 'delete']
  )
  assert.deepEqual(
    calls.map((call) => call.url),
    [
      '/api/admin/knowledge/documents',
      '/api/admin/knowledge/documents',
      '/api/admin/knowledge/documents/7/versions',
      '/api/admin/knowledge/documents/7/publish',
      '/api/admin/knowledge/documents/7/disable',
      '/api/admin/knowledge/versions/12/retry',
      '/api/admin/knowledge/documents/7'
    ]
  )
  assert.equal(calls[1].data.get('title'), '馆规')
  assert.equal(calls[1].data.get('file').size, 6)
  assert.equal(calls[2].data.has('file'), true)
  assert.equal(calls[3].params.version_id, 12)
  assert.equal(calls[1].headers, undefined, 'browser must set the multipart boundary')
  await api.searchKnowledgeApi({ query: 'R-204', strategy: 'hybrid_rerank', limit: 4 })
  await api.getKnowledgeIndexStatusApi(12)
  assert.equal(calls[7].url, '/api/admin/knowledge/search')
  assert.equal(calls[7].method, 'post')
  assert.equal(calls[7].data.strategy, 'hybrid_rerank')
  assert.equal(calls[7].timeout, 65000)
  assert.equal(calls[8].url, '/api/admin/knowledge/versions/12/index-status')
})
