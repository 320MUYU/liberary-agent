<script setup>
import { computed, ref } from 'vue'
import { renderAiMarkdown } from '@/utils/aiMarkdown'

const props = defineProps({ content: { type: String, default: '' }, allowRaw: Boolean })
const raw = ref(false)
const html = computed(() => renderAiMarkdown(props.content))
</script>

<template>
  <div class="ai-answer-content">
    <div v-if="allowRaw" class="answer-view-switch" aria-label="回答显示方式">
      <button type="button" :aria-pressed="!raw" @click="raw = false">阅读视图</button>
      <button type="button" :aria-pressed="raw" @click="raw = true">原始文本</button>
    </div>
    <pre v-if="raw" class="ai-raw-text">{{ content }}</pre>
    <div v-else class="ai-markdown" v-html="html"></div>
  </div>
</template>

<style scoped>
.ai-answer-content {
  min-width: 0;
  max-width: 100%;
  font-size: 14px;
  line-height: 1.85;
  overflow-wrap: anywhere;
}
.answer-view-switch {
  display: flex;
  gap: 4px;
  margin-bottom: 16px;
}
.answer-view-switch button {
  border: 1px solid #d7e2dc;
  border-radius: 6px;
  background: white;
  padding: 5px 12px;
  color: #65766e;
  cursor: pointer;
  font: inherit;
  font-size: 12px;
}
.answer-view-switch button[aria-pressed='true'] {
  background: #e8f2eb;
  color: #2b6144;
  border-color: #9db9a7;
}
.ai-raw-text {
  white-space: pre-wrap;
  font: inherit;
  margin: 0;
}
.ai-markdown {
  white-space: normal;
}
.ai-markdown :deep(> :first-child) {
  margin-top: 0;
}
.ai-markdown :deep(> :last-child) {
  margin-bottom: 0;
}
.ai-markdown :deep(p) {
  margin: 0 0 14px;
}
.ai-markdown :deep(h1),
.ai-markdown :deep(h2),
.ai-markdown :deep(h3),
.ai-markdown :deep(h4),
.ai-markdown :deep(h5),
.ai-markdown :deep(h6) {
  font-size: 1.1em;
  line-height: 1.6;
  margin: 22px 0 10px;
  font-weight: 650;
  color: #254a38;
}
.ai-markdown :deep(ul),
.ai-markdown :deep(ol) {
  padding-left: 24px;
  margin: 10px 0 16px;
}
.ai-markdown :deep(li) {
  padding-left: 3px;
  margin: 5px 0;
}
.ai-markdown :deep(li > p) {
  margin-bottom: 6px;
}
.ai-markdown :deep(strong) {
  font-weight: 650;
  color: #254a38;
}
.ai-markdown :deep(blockquote) {
  border-left: 3px solid #a1baa9;
  padding: 10px 16px;
  margin: 16px 0;
  background: #f3f7f4;
  color: #566c60;
}
.ai-markdown :deep(a) {
  color: #326a4d;
  text-decoration: underline;
  text-underline-offset: 3px;
}
.ai-markdown :deep(code) {
  font-family: Consolas, monospace;
  font-size: 0.92em;
  padding: 2px 5px;
  background: #eaf0ec;
  border-radius: 4px;
}
.ai-markdown :deep(pre) {
  max-width: 100%;
  overflow-x: auto;
  white-space: pre;
  background: #f3f5f3;
  border: 1px solid #dce4de;
  padding: 14px;
  border-radius: 8px;
  line-height: 1.65;
}
.ai-markdown :deep(pre code) {
  padding: 0;
  background: none;
}
.ai-markdown :deep(.ai-table-scroll) {
  max-width: 100%;
  overflow-x: auto;
  margin: 16px 0;
}
.ai-markdown :deep(table) {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.ai-markdown :deep(th),
.ai-markdown :deep(td) {
  padding: 9px 12px;
  border: 1px solid #dce4de;
  text-align: left;
  min-width: 100px;
}
.ai-markdown :deep(th) {
  background: #eef4ef;
  font-weight: 600;
}
.ai-markdown :deep(hr) {
  border: 0;
  border-top: 1px solid #dce4de;
  margin: 20px 0;
}
</style>
