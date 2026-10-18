import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'
import * as Vue from 'vue'
import { compile } from '@vue/compiler-dom'
import { renderToString } from '@vue/server-renderer'
import { renderAiMarkdown } from '../src/utils/aiMarkdown.js'

test('answers render headings, lists, emphasis and citations without rewriting facts', () => {
  const input =
    '## 结论\n\n**不能续借**。[1]\n\n- 被其他读者预约的图书不能续借。[1]\n- 原馆规定适用于华科。'
  const html = renderAiMarkdown(input)
  assert.match(html, /<h2>结论<\/h2>/)
  assert.match(html, /<strong>不能续借<\/strong>/)
  assert.match(html, /<ul>/)
  assert.equal((html.match(/\[1\]/g) || []).length, 2)
  assert.match(html, /原馆规定适用于华科/)
})

test('plain paragraphs, line breaks, code and mobile tables remain readable', () => {
  const html = renderAiMarkdown(
    '第一段\n第二行\n\n第二段\n\n| 条件 | 结果 |\n| --- | --- |\n| 已预约 | 不可续借 |\n\n```html\n<script>bad()</script>\n```'
  )
  assert.match(html, /第一段<br>\n第二行/)
  assert.match(html, /<p>第二段<\/p>/)
  assert.match(html, /class="ai-table-scroll"/)
  assert.match(html, /<table>/)
  assert.match(html, /&lt;script&gt;bad\(\)&lt;\/script&gt;/)
})

test('untrusted model text cannot execute HTML, scripts or unsafe links', () => {
  const html = renderAiMarkdown(
    '<img src=x onerror="bad()">\n\n[打开](javascript:bad())\n\n[资料](https://example.org/rules)\n\n![追踪](https://example.org/pixel)'
  )
  assert.ok(!html.includes('<img'))
  assert.ok(!html.includes('href="javascript:'))
  assert.match(html, /&lt;img/)
  assert.match(html, /rel="noopener noreferrer"/)
  assert.match(html, /href="https:\/\/example.org\/rules"/)
})

test('reviewer can inspect exact raw text while reading mode renders the same saved answer', async () => {
  const content = '**结论**\n\n- 可借20册。[1]\n<script>bad()</script>'
  const file = await readFile(
    new URL('../src/components/AiAnswerContent.vue', import.meta.url),
    'utf8'
  )
  const context = vm.createContext({ defineProps: () => ({ content, allowRaw: true }) })
  const module = new vm.SourceTextModule(
    file.match(/<script setup>([\s\S]*?)<\/script>/)[1] + '\nexport { raw, html, props }',
    { context }
  )
  const dependencies = {
    vue: { ref: Vue.ref, computed: Vue.computed },
    '@/utils/aiMarkdown': { renderAiMarkdown }
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
  const render = new Function(
    'Vue',
    compile(file.match(/<template>([\s\S]*?)<\/template>/)[1], {
      mode: 'function',
      prefixIdentifiers: true
    }).code
  )(Vue)
  const renderAnswer = () =>
    renderToString(
      Vue.createSSRApp({ render, setup: () => ({ ...module.namespace, content, allowRaw: true }) })
    )
  assert.match(await renderAnswer(), /<strong>结论<\/strong>/)
  module.namespace.raw.value = true
  const raw = await renderAnswer()
  assert.ok(raw.includes('**结论**\n\n- 可借20册。[1]'))
  assert.ok(raw.includes('&lt;script&gt;bad()&lt;/script&gt;'))
  assert.equal(module.namespace.props.content, content)
})
