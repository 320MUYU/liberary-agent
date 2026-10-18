<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import AiAnswerContent from '@/components/AiAnswerContent.vue'
import { getUserInfo } from '@/auth'
import {
  listEvaluationRuns,
  getEvaluationRun,
  getEvaluationCase,
  importEvaluationReport,
  saveEvaluationReview,
  exportEvaluationReviews
} from '@/api/evaluationReviewApi'
import {
  percent,
  filterCases,
  citedSources,
  reviewForm,
  reviewLabel
} from '@/utils/evaluationReview'

const runs = ref([])
const run = ref(null)
const currentCase = ref(null)
const form = ref(reviewForm({}))
const filter = ref('all')
const busy = ref(false)
const error = ref('')
const notice = ref('')
const baseline = ref('')
const fileInput = ref(null)
const storageKey = `evaluation-review-position-${getUserInfo()?.id}`
let active = true
const dirty = computed(() => !!currentCase.value && JSON.stringify(form.value) !== baseline.value)
const visibleCases = computed(() => filterCases(run.value?.cases || [], filter.value))
const sources = computed(() => citedSources(currentCase.value))
const metrics = computed(() => run.value?.metrics || {})

function discardChanges() {
  return !dirty.value || window.confirm('当前判断尚未保存，确定放弃这些修改？')
}

function beforeUnload(event) {
  if (dirty.value || busy.value) {
    event.preventDefault()
    event.returnValue = ''
  }
}

function remember() {
  try {
    localStorage.setItem(
      storageKey,
      JSON.stringify({ runId: run.value.id, caseId: currentCase.value?.id })
    )
  } catch {
    /* The server still preserves saved decisions when local storage is unavailable. */
  }
}

function restorePosition() {
  try {
    return JSON.parse(localStorage.getItem(storageKey) || '{}')
  } catch {
    return {}
  }
}

function applyCase(row) {
  currentCase.value = row
  form.value = reviewForm(row.review)
  baseline.value = JSON.stringify(form.value)
  remember()
}

async function fetchRun(id, caseId) {
  const detail = await getEvaluationRun(id)
  const nextId =
    detail.cases.find((row) => row.id === caseId)?.id ||
    detail.cases.find((row) => row.review.status !== 'reviewed')?.id ||
    detail.cases[0]?.id
  const row = nextId ? await getEvaluationCase(id, nextId) : null
  if (!active) return
  run.value = detail
  if (row) applyCase(row)
  else currentCase.value = null
}

async function initialize() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    const available = await listEvaluationRuns()
    if (!active) return
    runs.value = available
    const position = restorePosition()
    const chosen =
      available.find((row) => row.id === position.runId) ||
      available.find((row) => row.metrics.total === 16) ||
      available[0]
    if (chosen) await fetchRun(chosen.id, position.runId === chosen.id ? position.caseId : null)
  } catch (e) {
    if (active) error.value = e.message || '载入失败，请重试'
  } finally {
    if (active) busy.value = false
  }
}

async function loadRun(id) {
  if (busy.value || !discardChanges()) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    await fetchRun(id, run.value?.id === id ? currentCase.value?.id : null)
  } catch (e) {
    if (active) error.value = e.message || '载入失败'
  } finally {
    if (active) busy.value = false
  }
}

async function selectCase(id) {
  if (busy.value || !discardChanges()) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const row = await getEvaluationCase(run.value.id, id)
    if (active) applyCase(row)
  } catch (e) {
    if (active) error.value = e.message || '载入失败'
  } finally {
    if (active) busy.value = false
  }
}

async function save(status) {
  if (busy.value || !currentCase.value) return
  if (
    status === 'reviewed' &&
    (typeof form.value.answer_correct !== 'boolean' ||
      typeof form.value.citations_support !== 'boolean')
  ) {
    error.value = '提交前请选择回答正确性与引用支持性'
    return
  }
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const row = await saveEvaluationReview(run.value.id, currentCase.value.id, {
      ...form.value,
      status,
      revision: currentCase.value.review.revision
    })
    if (!active) return
    applyCase(row)
    notice.value = status === 'reviewed' ? '审核已提交' : '草稿已保存，尚未计入人工指标'
    try {
      const detail = await getEvaluationRun(run.value.id)
      if (active) {
        run.value = detail
        runs.value = runs.value.map((item) => (item.id === detail.id ? detail : item))
      }
    } catch {
      if (active) error.value = '判断已保存，统计刷新失败；请重新载入报告'
    }
  } catch (e) {
    if (active)
      error.value = `${e.message || '保存失败'}。当前输入已保留；可重试或重新载入最新判断。`
  } finally {
    if (active) busy.value = false
  }
}

async function importFile(event) {
  const file = event.target.files?.[0]
  if (!file || busy.value || !discardChanges()) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    if (file.size > 10 * 1024 * 1024) throw Error('报告不能超过10MB')
    const report = JSON.parse((await file.text()).replace(/^\uFEFF/, ''))
    const imported = await importEvaluationReport({
      name: file.name.replace(/\.json$/i, '').slice(0, 150) || '评测报告',
      report
    })
    const available = await listEvaluationRuns()
    if (!active) return
    runs.value = available
    await fetchRun(imported.id)
    if (active) {
      filter.value = 'all'
      notice.value = '报告已载入；重复导入会保留已有审核进度'
    }
  } catch (e) {
    if (active) error.value = e.message || '导入失败，请选择有效的回答报告 JSON'
  } finally {
    event.target.value = ''
    if (active) busy.value = false
  }
}

async function download(kind) {
  if (busy.value || !run.value) return
  busy.value = true
  error.value = ''
  try {
    const data = await exportEvaluationReviews(run.value.id, kind)
    if (!active) return
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(data, null, 2) + '\n'], { type: 'application/json' })
    )
    const link = document.createElement('a')
    link.href = url
    link.download = `${run.value.report_id}.${kind}.json`
    link.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    if (active) error.value = e.message || '导出失败'
  } finally {
    if (active) busy.value = false
  }
}

onBeforeRouteLeave(() => !busy.value && discardChanges())
onMounted(() => {
  window.addEventListener('beforeunload', beforeUnload)
  return initialize()
})
onUnmounted(() => {
  active = false
  window.removeEventListener('beforeunload', beforeUnload)
})
</script>

<template>
  <section class="evaluation-review" :aria-busy="busy">
    <div class="review-header">
      <div>
        <h2>逐题核对，留下判断</h2>
        <p>对照回答、实际引用摘录和完整原文，分别判断正确性与引用支持性。</p>
      </div>
      <el-button :disabled="busy" @click="fileInput.click()">导入报告 JSON</el-button>
      <input
        ref="fileInput"
        type="file"
        accept=".json,application/json"
        hidden
        @change="importFile"
      />
    </div>
    <div v-if="error" class="review-error" role="alert">{{ error }}</div>
    <p v-if="notice" class="review-notice" role="status">{{ notice }}</p>
    <div class="report-toolbar">
      <el-select
        :model-value="run?.id"
        placeholder="选择评测报告"
        :disabled="busy"
        aria-label="选择评测报告"
        @change="loadRun"
      >
        <el-option
          v-for="item in runs"
          :key="item.id"
          :value="item.id"
          :label="`${item.name} · ${item.metrics.total} 条`"
        />
      </el-select>
      <el-button :disabled="busy" @click="run ? loadRun(run.id) : initialize()">重新载入</el-button>
      <el-button :disabled="busy || !run" @click="download('reviews')">导出人工判断</el-button>
      <el-button :disabled="busy || !run" @click="download('report')">导出汇总报告</el-button>
    </div>
    <template v-if="run">
      <div class="report-info">
        <el-tag v-if="run.synthetic" type="warning">合成测试报告</el-tag
        ><span>报告 {{ run.report_id }}</span>
      </div>
      <div class="review-metrics">
        <article>
          <span>审核进度</span><strong>{{ metrics.human_reviewed }} / {{ metrics.total }}</strong
          ><small
            >覆盖率 {{ percent(metrics.human_review_coverage) }} · 草稿 {{ run.drafts }}</small
          >
        </article>
        <article>
          <span>回答正确率</span><strong>{{ percent(metrics.answer_accuracy) }}</strong
          ><small>仅统计已提交的人工判断</small>
        </article>
        <article>
          <span>引用支持率</span><strong>{{ percent(metrics.citation_support_rate) }}</strong
          ><small>仅统计已提交的人工判断</small>
        </article>
        <article>
          <span>自动契约通过率</span><strong>{{ percent(metrics.contract_pass_rate) }}</strong
          ><small>人工正确性需逐题确认</small>
        </article>
      </div>
      <div class="review-workspace">
        <aside class="case-sidebar">
          <label for="review-filter">筛选题目</label>
          <select id="review-filter" v-model="filter" :disabled="busy">
            <option value="all">全部</option>
            <option value="pending">待审核（含草稿）</option>
            <option value="reviewed">已审核</option>
            <option value="human_negative">人工未通过</option>
            <option value="automatic_failure">自动未通过</option>
          </select>
          <p class="case-count">{{ visibleCases.length }} 条题目</p>
          <div class="case-list">
            <button
              v-for="item in visibleCases"
              :key="item.id"
              :disabled="busy"
              :class="{ selected: currentCase?.id === item.id }"
              :aria-current="currentCase?.id === item.id ? 'true' : undefined"
              class="review-case"
              @click="selectCase(item.id)"
            >
              <span
                ><b>{{ item.id }}</b
                ><em>{{ reviewLabel(item.review.status) }}</em></span
              >
              <p>{{ item.question }}</p>
              <small v-if="!item.contract_pass">自动契约未通过</small>
            </button>
            <p v-if="!visibleCases.length">此筛选下暂无题目。</p>
          </div>
        </aside>
        <main v-if="currentCase" class="case-detail">
          <div class="case-heading">
            <span>{{ currentCase.id }}</span
            ><el-tag>{{ reviewLabel(currentCase.review.status) }}</el-tag
            ><span v-if="dirty" class="unsaved">有未保存修改</span>
          </div>
          <h3>{{ currentCase.question }}</h3>
          <section v-if="currentCase.prelude?.length" class="evidence-block">
            <h4>前序问题</h4>
            <ol>
              <li v-for="(text, index) in currentCase.prelude" :key="index">{{ text }}</li>
            </ol>
            <p class="hint">报告仅保留这些前序问题；历史回答需结合原始运行记录核对。</p>
          </section>
          <div v-if="currentCase.error" class="review-error">服务错误：{{ currentCase.error }}</div>
          <section class="evidence-block answer-block">
            <h4>实际回答</h4>
            <AiAnswerContent :content="currentCase.answer?.content || '（无回答）'" allow-raw />
          </section>
          <section class="evidence-block">
            <h4>预期事实与标注证据</h4>
            <ul>
              <li v-for="(fact, index) in currentCase.expected_facts" :key="index">{{ fact }}</li>
            </ul>
            <p v-if="!currentCase.expected_facts?.length">本题预期拒答，请核对拒答范围与措辞。</p>
            <blockquote v-for="(item, index) in currentCase.expected_evidence" :key="index">
              <small>{{ item.source_key }}</small>
              <pre>{{ item.quote }}</pre>
            </blockquote>
          </section>
          <section class="evidence-block">
            <h4>实际返回的来源摘录</h4>
            <p class="hint">以下是回答携带的摘录；“正文已引用”表示答案中出现了该编号。</p>
            <article v-for="(source, index) in sources" :key="index" class="source-excerpt">
              <b>[{{ source.number }}] {{ source.title }}</b
              ><el-tag :type="source.cited ? 'success' : 'info'" size="small">{{
                source.cited ? '正文已引用' : '正文未引用'
              }}</el-tag>
              <p class="hint">
                文档 {{ source.document_id }} · 版本 {{ source.version }} · 片段
                {{ source.chunk_id }}
              </p>
              <pre>{{ source.excerpt || '（未提供摘录）' }}</pre>
            </article>
            <p v-if="!sources.length">无来源摘录</p>
          </section>
          <section class="evidence-block">
            <h4>完整来源预览</h4>
            <p class="hint">展开核对报告保存的完整片段，判断实际引用是否足以支持回答。</p>
            <details v-for="(preview, index) in currentCase.previews" :key="index">
              <summary>
                {{ preview.title || '来源原文' }} · 文档 {{ preview.document_id }} · 版本
                {{ preview.version }} · 片段 {{ preview.chunk_id }}
              </summary>
              <pre>{{ preview.text }}</pre>
            </details>
            <p v-if="!currentCase.previews?.length">报告未保存完整来源预览</p>
          </section>
          <form class="decision-form" @submit.prevent="save('reviewed')">
            <h4>人工判断</h4>
            <fieldset :disabled="busy">
              <legend>回答是否正确？</legend>
              <label
                ><input
                  v-model="form.answer_correct"
                  type="radio"
                  name="answer_correct"
                  :value="true"
                />正确</label
              ><label
                ><input
                  v-model="form.answer_correct"
                  type="radio"
                  name="answer_correct"
                  :value="false"
                />错误或有遗漏</label
              >
            </fieldset>
            <fieldset :disabled="busy">
              <legend>引用是否支持回答？</legend>
              <label
                ><input
                  v-model="form.citations_support"
                  type="radio"
                  name="citations_support"
                  :value="true"
                />支持（拒答题：无不当引用）</label
              ><label
                ><input
                  v-model="form.citations_support"
                  type="radio"
                  name="citations_support"
                  :value="false"
                />不支持或证据不足</label
              >
            </fieldset>
            <label for="review-notes">审核备注</label
            ><el-input
              id="review-notes"
              v-model="form.notes"
              :disabled="busy"
              type="textarea"
              :rows="3"
              maxlength="10000"
              placeholder="记录遗漏、歧义或需要复核的证据"
            />
            <p class="hint">
              草稿不计入人工指标。将已审核题目保存为草稿会暂时移出统计，需再次提交。
            </p>
            <p v-if="currentCase.review.reviewer" class="hint">
              最近修改：{{ currentCase.review.reviewer }} · {{ currentCase.review.updated_at }} ·
              版本 {{ currentCase.review.revision }}
            </p>
            <div class="decision-actions">
              <el-button :disabled="busy" @click="save('draft')">保存草稿</el-button
              ><el-button type="primary" native-type="submit" :loading="busy" :disabled="busy"
                >提交审核</el-button
              ><el-button :disabled="busy" @click="selectCase(currentCase.id)"
                >重新载入本题</el-button
              >
            </div>
          </form>
        </main>
      </div>
      <p class="hint">导出仅包含服务器上已提交的判断；草稿和未保存修改不计入结果。</p>
    </template>
    <el-empty v-else-if="!busy" description="导入一份回答评测报告，开始逐题审核" />
  </section>
</template>

<style scoped>
.evaluation-review {
  max-width: 1440px;
  margin: 0 auto;
  color: #243d36;
}
.review-header,
.report-toolbar,
.case-heading,
.decision-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.review-header {
  justify-content: space-between;
  margin-bottom: 20px;
}
h2 {
  font-size: 23px;
  margin: 0 0 8px;
}
h3 {
  font-size: 21px;
  line-height: 1.6;
}
h4 {
  margin: 0 0 12px;
  font-size: 16px;
}
p {
  line-height: 1.7;
}
.review-header p,
.hint,
.case-count {
  color: #697b74;
  font-size: 13px;
}
.report-toolbar {
  margin-bottom: 16px;
}
.report-toolbar .el-select {
  width: min(100%, 360px);
}
.report-info {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 12px;
  overflow-wrap: anywhere;
}
.review-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin: 18px 0 24px;
}
.review-metrics article {
  background: white;
  border: 1px solid #dce5df;
  border-radius: 14px;
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.review-metrics span {
  color: #697b74;
  font-size: 13px;
}
.review-metrics strong {
  font-size: 26px;
}
.review-metrics small {
  color: #697b74;
  font-size: 12px;
}
.review-workspace {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 20px;
  align-items: start;
}
.case-sidebar,
.case-detail {
  background: white;
  border: 1px solid #dce5df;
  border-radius: 14px;
  padding: 20px;
  min-width: 0;
}
.case-sidebar {
  position: sticky;
  top: 16px;
}
.case-sidebar label {
  display: block;
  margin-bottom: 8px;
  font-size: 14px;
}
.case-sidebar select {
  width: 100%;
  padding: 8px;
  border: 1px solid #cbd8d0;
  border-radius: 6px;
  background: white;
  color: inherit;
}
.case-list {
  max-height: 65vh;
  overflow: auto;
}
.review-case {
  display: block;
  text-align: left;
  width: 100%;
  padding: 12px;
  margin: 8px 0;
  background: #f8faf8;
  border: 1px solid transparent;
  border-radius: 8px;
  cursor: pointer;
  color: inherit;
  overflow-wrap: anywhere;
}
.review-case.selected {
  border-color: #438060;
  background: #edf6ef;
}
.review-case span {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
}
.review-case em {
  font-style: normal;
  white-space: nowrap;
  color: #64816d;
}
.review-case p {
  margin: 8px 0 0;
  font-size: 13px;
}
.review-case small,
.unsaved {
  color: #a6632a;
  font-size: 12px;
}
.case-heading {
  color: #697b74;
  font-size: 13px;
  overflow-wrap: anywhere;
}
.evidence-block {
  margin: 24px 0;
}
.answer-block {
  padding: 18px;
  border-radius: 10px;
  background: #f1f6f2;
}
pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font: inherit;
  line-height: 1.85;
  margin: 8px 0;
}
blockquote {
  border-left: 3px solid #9cb8a5;
  margin: 14px 0;
  padding: 4px 14px;
  background: #f8faf8;
}
.source-excerpt {
  border: 1px solid #dce5df;
  padding: 16px;
  border-radius: 8px;
  margin: 12px 0;
}
.source-excerpt .el-tag {
  margin-left: 8px;
}
details {
  border-bottom: 1px solid #e5eae6;
  padding: 12px 0;
}
summary {
  cursor: pointer;
  line-height: 1.7;
  overflow-wrap: anywhere;
}
.decision-form {
  border-top: 1px solid #dce5df;
  padding-top: 24px;
}
fieldset {
  border: 0;
  margin: 18px 0;
  padding: 0;
}
legend {
  font-size: 14px;
  margin-bottom: 10px;
}
fieldset label {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  margin: 6px 18px 6px 0;
  font-size: 14px;
}
.decision-form > label {
  display: block;
  font-size: 14px;
  margin-bottom: 10px;
}
.review-error {
  background: #fff1ee;
  color: #a33e31;
  padding: 12px 16px;
  border-radius: 8px;
  margin: 12px 0;
  line-height: 1.7;
}
.review-notice {
  color: #356845;
}
button:disabled {
  cursor: wait;
}
@media (max-width: 1100px) {
  .review-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .review-workspace {
    grid-template-columns: 230px minmax(0, 1fr);
    gap: 12px;
  }
}
@media (max-width: 760px) {
  .review-workspace {
    grid-template-columns: minmax(0, 1fr);
  }
  .case-sidebar {
    position: static;
  }
  .case-list {
    max-height: 210px;
  }
  .case-detail,
  .case-sidebar {
    padding: 16px;
  }
  .review-metrics article {
    padding: 14px;
  }
  .review-metrics strong {
    font-size: 22px;
  }
}
</style>
