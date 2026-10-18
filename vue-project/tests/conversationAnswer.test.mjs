import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'
import * as Vue from 'vue'
import { compile } from '@vue/compiler-dom'
import { renderToString } from '@vue/server-renderer'

test('source preview renders the API text field as escaped original text', async () => {
  const file = await readFile(
    new URL('../src/components/ConversationAnswer.vue', import.meta.url),
    'utf8'
  )
  const fixture = {
    chunk_id: 21,
    document_id: 8,
    title: '图书续借',
    version: 1,
    text: '每册图书可续借一次。<script>unexpected()</script>'
  }
  const context = vm.createContext({ defineProps: () => {} })
  const module = new vm.SourceTextModule(
    file.match(/<script setup>([\s\S]*?)<\/script>/)[1] +
      '\nexport { preview, source, visible, loading, error }',
    { context }
  )
  const dependencies = {
    '@/components/AiAnswerContent.vue': { default: {} },
    vue: { ref: Vue.ref },
    '@/api/knowledgeApi': {
      getKnowledgeSourceApi: async (id) => {
        assert.equal(id, fixture.chunk_id)
        return fixture
      }
    }
  }
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
  await module.namespace.preview({ chunk_id: fixture.chunk_id })
  const template = file.match(/<template>([\s\S]*)<\/template>/)[1]
  const render = new Function(
    'Vue',
    compile(template, { mode: 'function', prefixIdentifiers: true }).code
  )(Vue)
  const app = Vue.createSSRApp({
    render,
    setup: () => ({ ...module.namespace, result: { content: '可以续借一次。[1]' } })
  })
  app.component('el-dialog', {
    setup:
      (_, { slots }) =>
      () =>
        Vue.h('div', slots.default?.())
  })
  app.component('AiAnswerContent', {
    props: ['content'],
    render() {
      return Vue.h('div', this.content)
    }
  })
  const html = await renderToString(app)
  assert.ok(html.includes('每册图书可续借一次。'))
  assert.ok(html.includes('&lt;script&gt;unexpected()&lt;/script&gt;'))
  assert.ok(!html.includes('<script>'))
})
