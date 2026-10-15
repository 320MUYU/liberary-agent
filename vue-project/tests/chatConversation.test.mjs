import test from 'node:test'
import assert from 'node:assert/strict'

import { buildChatHistory, retrievalLabel } from '../src/utils/chatConversation.js'

test('history excludes local welcome and previously failed questions', () => {
  assert.deepEqual(
    buildChatHistory([
      { role: 'assistant', text: 'welcome', localOnly: true },
      { role: 'user', text: 'failed', failed: true },
      { role: 'user', text: 'question' }
    ]),
    [{ role: 'user', content: 'question' }]
  )
})

test('history observes all server budgets and preserves latest question', () => {
  const messages = Array.from({ length: 40 }, (_, index) => ({
    role: index % 2 ? 'user' : 'assistant',
    text: `${index}:` + '测'.repeat(4100)
  }))
  const history = buildChatHistory(messages)
  assert.ok(history.length <= 30)
  assert.ok(history.every((message) => message.content.length <= 4000))
  assert.ok(history.reduce((sum, message) => sum + message.content.length, 0) <= 20000)
  assert.equal(history.at(-1).role, 'user')
  assert.ok(history.at(-1).content.startsWith('39:'))
})

test('status labels never present unknown or failed retrieval as a match', () => {
  assert.match(retrievalLabel('matched'), /依据/)
  assert.match(retrievalLabel('no_match'), /未找到/)
  assert.match(retrievalLabel('insufficient_evidence'), /不足/)
  assert.equal(retrievalLabel('not_requested'), '普通聊天 · 未检索知识库')
  assert.equal(retrievalLabel(undefined), '')
})
