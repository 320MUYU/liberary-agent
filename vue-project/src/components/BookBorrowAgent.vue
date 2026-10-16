<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import {
  startBorrowRun,
  getBorrowRun,
  selectBorrowBook,
  decideBorrow,
  retryBorrowRun
} from '@/api/agentApi'
import { getUserInfo } from '@/auth'
import { getKnowledgeSourceApi } from '@/api/knowledgeApi'
import { bookAvailability, canRequestLoan, discoveryDegradation } from '@/utils/library'

const query = ref('')
const run = ref(null)
const busy = ref(false)
const error = ref('')
const sourceDialog = ref(false)
const sourceLoading = ref(false)
const sourceContent = ref(null)
const sourceError = ref('')
const storageKey = `library-borrow-run-${getUserInfo()?.id}`
const runId = ref(sessionStorage.getItem(storageKey) || '')
let active = true
onUnmounted(() => {
  active = false
})

async function perform(operation) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    const result = await operation()
    if (active) run.value = result
  } catch (failure) {
    if (active) error.value = failure.message || '请求暂未完成，请刷新任务状态。'
  } finally {
    if (active) busy.value = false
  }
}

async function search() {
  if (busy.value || runId.value || !query.value.trim()) return
  if (query.value.trim().length > 1000) {
    error.value = '查找描述不能超过1000字。'
    return
  }
  runId.value = crypto.randomUUID()
  sessionStorage.setItem(storageKey, runId.value)
  await perform(() => startBorrowRun({ request_id: runId.value, query: query.value.trim() }))
}

async function select(bookId) {
  if (run.value?.status !== 'select_book') return
  if (!canRequestLoan(run.value.books.find((book) => book.id === bookId))) return
  await perform(() => selectBorrowBook(runId.value, bookId))
}

async function openSource(source) {
  if (sourceLoading.value) return
  sourceDialog.value = true
  sourceLoading.value = true
  sourceContent.value = null
  sourceError.value = ''
  try {
    const content = await getKnowledgeSourceApi(source.chunk_id)
    if (active) sourceContent.value = content
  } catch (failure) {
    if (active) sourceError.value = failure.message || '来源已停用或暂时不可用。'
  } finally {
    if (active) sourceLoading.value = false
  }
}

async function decide(confirmed) {
  if (run.value?.status !== 'confirm_borrow') return
  const actionId = run.value.action.id
  await perform(() => decideBorrow(runId.value, { action_id: actionId, confirmed }))
}

async function refresh() {
  if (runId.value) await perform(() => getBorrowRun(runId.value))
}

async function retry() {
  if (runId.value) await perform(() => retryBorrowRun(runId.value))
}

async function restart() {
  if (busy.value) return
  if (run.value?.status === 'confirm_borrow') {
    await decide(false)
    if (run.value?.status !== 'cancelled') return
  }
  run.value = null
  runId.value = ''
  error.value = ''
  sessionStorage.removeItem(storageKey)
}

onMounted(refresh)
</script>

<template>
  <div class="borrow-agent">
    <div class="borrow-intro">
      <span>找书 · 选择书目 · 确认申请</span>
      <h3>告诉我，你想找什么书？</h3>
      <p>查询实时馆藏。你确认后才提交借阅申请，借出仍由管理员办理。</p>
    </div>
    <form class="borrow-search" @submit.prevent="search">
      <el-input
        v-model="query"
        aria-label="找书需求"
        placeholder="例如：找多智能体相关的书，或推荐一些历史书"
        maxlength="1000"
        :disabled="busy || !!runId"
      />
      <el-button
        native-type="submit"
        type="primary"
        :loading="busy"
        :disabled="!!runId || !query.trim()"
        >查找图书</el-button
      >
    </form>
    <p v-if="busy" role="status">正在处理，请稍候…</p>
    <el-alert v-if="error" :title="error" type="warning" :closable="false" show-icon />
    <el-alert
      v-if="run?.degraded?.length"
      :title="discoveryDegradation(run.degraded)"
      type="warning"
      :closable="false"
      show-icon
    />
    <div v-if="runId" class="borrow-controls">
      <el-button :disabled="busy" @click="refresh">刷新任务状态</el-button>
      <el-button
        v-if="error || run?.status === 'retryable' || run?.status === 'confirmed'"
        :disabled="busy"
        @click="retry"
        >继续未完成任务</el-button
      >
      <el-button :disabled="busy" @click="restart">重新找书</el-button>
    </div>
    <section v-if="run?.status === 'select_book'" aria-label="可选书目">
      <p>{{ run.message }}</p>
      <div class="borrow-books">
        <article v-for="book in run.books" :key="book.id" class="borrow-book">
          <h4>{{ book.title }}</h4>
          <p>{{ book.author }} · {{ book.publisher || '出版社未登记' }}</p>
          <p v-if="book.isbn">ISBN {{ book.isbn }}</p>
          <p v-if="book.publication_year">{{ book.publication_year }} 年出版</p>
          <p class="stock">{{ bookAvailability(book) }}</p>
          <p class="muted">馆藏在查询或刷新时更新，提交时再次核验。</p>
          <div v-if="book.match_reasons?.length || book.sources?.length" class="book-evidence">
            <strong>匹配依据</strong>
            <p v-for="reason in book.match_reasons" :key="reason">{{ reason }}</p>
            <div v-for="source in book.sources" :key="source.chunk_id" class="book-source">
              <p>{{ source.excerpt }}</p>
              <el-button text :disabled="sourceLoading" @click="openSource(source)"
                >查看来源原文</el-button
              >
            </div>
            <p class="muted">依据为已登记的书目元数据，不代表书籍正文或适读年龄评估。</p>
          </div>
          <a
            v-if="book.source?.url"
            :href="book.source.url"
            target="_blank"
            rel="noopener noreferrer"
            >查看来源版次</a
          >
          <el-button :disabled="busy || !canRequestLoan(book)" @click="select(book.id)"
            >选择这本书</el-button
          >
        </article>
      </div>
    </section>
    <section
      v-else-if="run?.status === 'confirm_borrow'"
      class="borrow-confirm"
      aria-label="确认借阅申请"
    >
      <span>请核对本次申请</span>
      <h3>{{ run.action.book.title }}</h3>
      <p>{{ run.action.book.author }} · {{ run.action.book.publisher || '出版社未登记' }}</p>
      <p v-if="run.action.book.isbn">ISBN {{ run.action.book.isbn }}</p>
      <p>{{ run.action.message }}</p>
      <p class="muted">确认有效期为10分钟；提交时会重新检查可借状态。</p>
      <div class="borrow-controls">
        <el-button type="primary" :disabled="busy" @click="decide(true)">确认提交申请</el-button>
        <el-button :disabled="busy" @click="decide(false)">取消本次申请</el-button>
      </div>
    </section>
    <section v-else-if="run" class="borrow-result" role="status">
      <h3 v-if="run.status === 'pending'">借阅申请已提交 · 待管理员确认</h3>
      <p>{{ run.message }}</p>
      <p v-if="run.receipt?.loan_id">申请编号：{{ run.receipt.loan_id }}</p>
      <router-link v-if="run.status === 'pending'" to="/loans"
        >查看我的借阅与最新进度 →</router-link
      >
    </section>
    <el-dialog v-model="sourceDialog" title="书目来源原文" width="min(680px, 94vw)">
      <p v-if="sourceLoading" role="status">正在读取来源…</p>
      <el-alert v-if="sourceError" :title="sourceError" type="warning" :closable="false" />
      <template v-if="sourceContent">
        <h3>{{ sourceContent.title }} · 文档版本 {{ sourceContent.version }}</h3>
        <pre class="source-text">{{ sourceContent.text }}</pre>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.borrow-agent {
  padding: 26px;
  overflow-y: auto;
  min-height: 0;
}
.borrow-intro span,
.stock {
  color: #9a6b22;
  font-size: 13px;
}
.borrow-intro h3 {
  margin: 12px 0;
  font-size: 24px;
}
.borrow-agent p {
  line-height: 1.75;
  overflow-wrap: anywhere;
}
.borrow-search {
  display: flex;
  gap: 12px;
  margin: 24px 0;
}
.borrow-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin: 18px 0;
}
.borrow-controls .el-button {
  margin-left: 0;
}
.borrow-books {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 16px;
}
.borrow-book,
.borrow-confirm,
.borrow-result {
  border: 1px solid #e3ded4;
  border-radius: 14px;
  padding: 20px;
  background: #fcfbf8;
}
.borrow-book h4 {
  margin: 0 0 12px;
  font-size: 18px;
  overflow-wrap: anywhere;
}
.borrow-confirm {
  border-color: #c7ad7b;
}
.muted {
  color: #6f7780;
  font-size: 13px;
}
.book-evidence {
  margin: 12px 0;
  font-size: 13px;
}
.book-source {
  border-left: 2px solid #c7ad7b;
  padding-left: 10px;
  margin: 10px 0;
}
.source-text {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.7;
}
.borrow-book > a {
  display: block;
  margin: 12px 0;
}
@media (max-width: 600px) {
  .borrow-agent {
    padding: 16px;
  }
  .borrow-search {
    flex-direction: column;
  }
  .borrow-books {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
