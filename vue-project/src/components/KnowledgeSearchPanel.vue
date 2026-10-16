<script setup>
import { ref, onUnmounted } from 'vue'
import { searchKnowledgeApi } from '@/api/knowledgeApi'
import { formatRetrievalScore, validateRetrievalQuery } from '@/utils/knowledge'

const query = ref('')
const strategy = ref('current')
const result = ref(null)
const loading = ref(false)
const error = ref('')
const submittedQuery = ref('')
let active = true

async function runSearch() {
  if (loading.value) return
  error.value = validateRetrievalQuery(query.value)
  if (error.value) return
  loading.value = true
  result.value = null
  submittedQuery.value = query.value.trim()
  try {
    const data = await searchKnowledgeApi({
      query: submittedQuery.value,
      strategy: strategy.value,
      limit: 4
    })
    if (active) result.value = data
  } catch {
    if (active) error.value = '检索检查失败，请重试。'
  } finally {
    if (active) loading.value = false
  }
}

onUnmounted(() => {
  active = false
})
</script>

<template>
  <section class="retrieval-panel surface">
    <h3>检索效果检查</h3>
    <p class="hint">
      输入读者可能提出的问题，检查已发布资料的命中情况。选择不同方式可比较检索结果，此操作不会修改问答配置。
    </p>
    <form class="search-controls" @submit.prevent="runSearch">
      <el-input
        v-model="query"
        :disabled="loading"
        maxlength="1000"
        placeholder="例如：研讨室最晚什么时候可以取消？"
        aria-label="检索问题"
      />
      <el-select v-model="strategy" :disabled="loading" aria-label="检索方式">
        <el-option label="当前问答配置" value="current" />
        <el-option label="语义检索" value="vector" />
        <el-option label="混合检索" value="hybrid" />
        <el-option label="混合检索 + 重排" value="hybrid_rerank" />
      </el-select>
      <el-button type="primary" native-type="submit" :loading="loading">检查检索效果</el-button>
    </form>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div v-if="result" class="search-result" aria-live="polite">
      <p>
        <strong>{{ submittedQuery }}</strong>
      </p>
      <div class="result-summary">
        <span>{{ result.candidates.length }} 个候选 · {{ result.results.length }} 个入选片段</span>
        <span>检索耗时 {{ ((result.timings_ms.total || 0) / 1000).toFixed(2) }} 秒</span>
        <el-tag :type="result.rerank_status === 'fallback' ? 'warning' : 'info'">
          {{
            {
              applied: '已执行模型重排',
              fallback: '重排暂不可用，已回退到融合排序',
              disabled: '本次未执行模型重排'
            }[result.rerank_status]
          }}
        </el-tag>
      </div>
      <el-alert
        v-if="!result.results.length"
        title="没有达到筛选要求的片段，请检查资料是否已发布、问题是否有文档依据。"
        type="info"
        :closable="false"
      />
      <el-table
        v-if="result.candidates.length"
        :data="result.candidates"
        row-key="chunk_id"
        class="retrieval-table"
      >
        <el-table-column type="expand">
          <template #default="{ row }">
            <pre class="source-text">{{ row.text }}</pre>
          </template>
        </el-table-column>
        <el-table-column label="来源片段" min-width="260">
          <template #default="{ row }">
            <strong>{{ row.title }} · v{{ row.version }}</strong>
            <p class="location">
              {{ row.page ? `第 ${row.page} 页` : '' }} {{ row.section || '' }}
            </p>
            <p class="excerpt">
              {{ row.text.slice(0, 160) }}{{ row.text.length > 160 ? '…' : '' }}
            </p>
          </template>
        </el-table-column>
        <el-table-column label="召回渠道" width="125">
          <template #default="{ row }"
            ><div class="channel-tags">
              <el-tag v-for="channel in row.channels" :key="channel" size="small">{{
                channel === 'vector' ? '语义' : '关键词'
              }}</el-tag>
            </div></template
          >
        </el-table-column>
        <el-table-column label="排序" width="120">
          <template #default="{ row }"
            ><div>融合第 {{ row.fusion_rank }}</div>
            <el-tag v-if="row.selected_rank" size="small" type="success"
              >入选第 {{ row.selected_rank }}</el-tag
            ><span v-else class="hint">未入选</span></template
          >
        </el-table-column>
        <el-table-column label="相关性分数" min-width="165">
          <template #default="{ row }">
            <div>向量距离：{{ formatRetrievalScore(row.distance) }}</div>
            <div>关键词：{{ formatRetrievalScore(row.bm25_score) }}</div>
            <div>融合：{{ formatRetrievalScore(row.rrf_score) }}</div>
            <div>模型重排：{{ formatRetrievalScore(row.rerank_score) }}</div>
          </template>
        </el-table-column>
      </el-table>
      <p class="hint">
        展开行可核对原文。向量距离越小越接近，其余分数越高排名越靠前；不同分数不能直接比较，也不代表答案正确率。
      </p>
    </div>
  </section>
</template>

<style scoped>
.retrieval-panel {
  padding: 22px;
  min-width: 0;
}
h3 {
  margin: 0 0 10px;
}
.hint,
.location {
  color: #64748b;
  font-size: 13px;
  line-height: 1.7;
}
.search-controls {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 18px 0;
}
.search-controls .el-input {
  flex: 1;
  min-width: 160px;
}
.search-controls .el-select {
  width: 190px;
  flex-shrink: 0;
}
.result-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  margin: 14px 0;
  font-size: 13px;
}
.source-text {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  padding: 16px;
  margin: 0;
  font: inherit;
  line-height: 1.8;
}
.excerpt {
  line-height: 1.65;
  font-size: 13px;
  margin: 6px 0;
  overflow-wrap: anywhere;
}
.channel-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.location {
  margin: 4px 0;
}
.retrieval-table {
  width: 100%;
  margin-top: 12px;
}
@media (max-width: 720px) {
  .retrieval-panel {
    padding: 16px;
  }
  .search-controls {
    flex-direction: column;
    align-items: stretch;
  }
  .search-controls .el-input,
  .search-controls .el-select {
    width: 100%;
  }
}
</style>
