<script setup>
import { ref } from 'vue'
import { getKnowledgeSourceApi } from '@/api/knowledgeApi'

defineProps({ result: { type: Object, required: true } })
const visible = ref(false)
const loading = ref(false)
const source = ref(null)
const error = ref('')
async function preview(item) {
  if (loading.value) return
  visible.value = true
  loading.value = true
  source.value = null
  error.value = ''
  try {
    source.value = await getKnowledgeSourceApi(item.chunk_id)
  } catch (failure) {
    error.value = failure.message || '来源暂时不可用。'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="conversation-answer">
    <p class="answer-text">{{ result.content }}</p>
    <div v-if="result.sources?.length" class="answer-sources" aria-label="回答来源">
      <button
        v-for="item in result.sources"
        :key="item.chunk_id"
        :disabled="loading"
        @click="preview(item)"
      >
        [{{ item.number }}] {{ item.title }} · v{{ item.version }}
      </button>
    </div>
    <p
      v-if="['no_match', 'insufficient_evidence'].includes(result.retrieval_status)"
      class="evidence-note"
    >
      知识库依据不足，可补充问题或联系管理员确认。
    </p>
    <el-dialog v-model="visible" title="来源原文" width="min(680px, 94vw)" append-to-body>
      <p v-if="loading" role="status">正在读取来源…</p>
      <p v-else-if="error" role="alert">{{ error }}</p>
      <template v-else-if="source">
        <strong>{{ source.title }} · v{{ source.version }}</strong>
        <pre>{{ source.text }}</pre>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.answer-text,
pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.85;
  font: inherit;
}
.answer-sources {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 12px;
}
.answer-sources button {
  border: 1px solid #d8e7df;
  border-radius: 8px;
  padding: 7px 10px;
  background: #f0f6f2;
  color: var(--mint-dark);
  text-align: left;
  font-size: 12px;
}
.evidence-note {
  color: var(--muted);
  font-size: 12px;
  margin-top: 9px;
}
pre {
  margin-top: 16px;
}
</style>
