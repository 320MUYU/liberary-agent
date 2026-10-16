<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import {
  startBorrowRun,
  getBorrowRun,
  selectBorrowBook,
  decideBorrow,
  retryBorrowRun,
  selectReturnLoan,
  getLoanPage
} from '@/api/agentApi'
import { getUserInfo } from '@/auth'
import { getKnowledgeSourceApi } from '@/api/knowledgeApi'
import {
  bookAvailability,
  canRequestLoan,
  canRequestReturn,
  discoveryDegradation,
  LOAN_STATUSES,
  formatLoanTime
} from '@/utils/library'

const query = ref('')
const taskType = ref('borrow')
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
    if (active) {
      run.value = result
      if (result.task_type) taskType.value = result.task_type
    }
  } catch (failure) {
    if (active) error.value = failure.message || '请求暂未完成，请刷新任务状态。'
  } finally {
    if (active) busy.value = false
  }
}

async function search() {
  if (busy.value || runId.value || (taskType.value === 'borrow' && !query.value.trim())) return
  if (query.value.trim().length > 1000) {
    error.value = '查找描述不能超过1000字。'
    return
  }
  runId.value = crypto.randomUUID()
  sessionStorage.setItem(storageKey, runId.value)
  await perform(() =>
    startBorrowRun({
      request_id: runId.value,
      query:
        query.value.trim() ||
        (taskType.value === 'return' ? '查询我的借阅，我要申请归还' : '查询我的借阅'),
      task_type: taskType.value
    })
  )
}

async function select(bookId) {
  if (run.value?.status !== 'select_book') return
  if (!canRequestLoan(run.value.books.find((book) => book.id === bookId))) return
  await perform(() => selectBorrowBook(runId.value, bookId))
}

async function selectLoan(loanId) {
  if (run.value?.status !== 'select_loan') return
  if (!canRequestReturn(run.value.loans.find((loan) => loan.id === loanId))) return
  await perform(() => selectReturnLoan(runId.value, loanId))
}

async function changeLoanPage(page) {
  if (run.value?.status !== 'select_loan') return
  await perform(() => getLoanPage(runId.value, page))
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
  if (!['confirm_borrow', 'confirm_return'].includes(run.value?.status)) return
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
  if (['confirm_borrow', 'confirm_return'].includes(run.value?.status)) {
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
      <span>找书借阅 · 我的借阅 · 申请归还</span>
      <h3>{{ taskType === 'borrow' ? '告诉我，你想找什么书？' : '查看自己的借阅，准备下一步' }}</h3>
      <p>
        {{
          taskType === 'borrow'
            ? '查询实时馆藏。你确认后才提交借阅申请，借出仍由管理员办理。'
            : '选择借阅中的记录并确认后提交归还申请；交还实体图书后，由管理员确认归还。'
        }}
      </p>
    </div>
    <el-radio-group
      v-model="taskType"
      class="task-types"
      aria-label="借阅助手任务"
      :disabled="busy || !!runId"
    >
      <el-radio-button value="borrow">找书借阅</el-radio-button>
      <el-radio-button value="my_loans">我的借阅</el-radio-button>
      <el-radio-button value="return">申请归还</el-radio-button>
    </el-radio-group>
    <form class="borrow-search" @submit.prevent="search">
      <el-input
        v-model="query"
        aria-label="找书需求"
        :placeholder="
          taskType === 'borrow'
            ? '例如：找多智能体相关的书，或推荐一些历史书'
            : '可选：查询借阅中的《史记》；留空查询全部记录'
        "
        maxlength="1000"
        :disabled="busy || !!runId"
      />
      <el-button
        native-type="submit"
        type="primary"
        :loading="busy"
        :disabled="!!runId || (taskType === 'borrow' && !query.trim())"
        >{{ taskType === 'borrow' ? '查找图书' : '查询我的借阅' }}</el-button
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
      <el-button :disabled="busy" @click="restart">开始新任务</el-button>
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
    <section v-else-if="run?.status === 'select_loan'" aria-label="我的借阅记录">
      <p>{{ run.message }}</p>
      <p v-if="!run.loans.length" class="muted">当前没有符合条件的借阅记录。</p>
      <div class="borrow-books">
        <article v-for="loan in run.loans" :key="loan.id" class="borrow-book loan-card">
          <h4>{{ loan.book_title }}</h4>
          <el-tag :type="LOAN_STATUSES[loan.status]?.type || 'info'">{{
            LOAN_STATUSES[loan.status]?.label || '状态待确认'
          }}</el-tag>
          <p>借阅编号：{{ loan.id }}</p>
          <p>副本条码：{{ loan.barcode || '尚未分配' }}</p>
          <p>借出时间：{{ formatLoanTime(loan.borrowed_at) }}</p>
          <p>应还时间：{{ formatLoanTime(loan.due_at) }}</p>
          <p v-if="loan.is_overdue" class="stock">已逾期，请尽快交还实体图书。</p>
          <p v-if="loan.status === 'return_pending'" class="muted">
            已申请归还，请交还实体图书并等待管理员确认。
          </p>
          <el-button :disabled="busy || !canRequestReturn(loan)" @click="selectLoan(loan.id)"
            >申请归还这本书</el-button
          >
        </article>
      </div>
      <div class="borrow-controls" aria-label="借阅记录分页">
        <el-button
          :disabled="busy || run.loan_page.page <= 1"
          @click="changeLoanPage(run.loan_page.page - 1)"
          >上一页</el-button
        >
        <span>第 {{ run.loan_page.page }} 页 · 共 {{ run.loan_page.total }} 条</span>
        <el-button
          :disabled="busy || run.loan_page.page * run.loan_page.page_size >= run.loan_page.total"
          @click="changeLoanPage(run.loan_page.page + 1)"
          >下一页</el-button
        >
      </div>
    </section>
    <section
      v-else-if="run?.status === 'confirm_return'"
      class="borrow-confirm"
      aria-label="确认归还申请"
    >
      <span>请核对本次归还</span>
      <h3>{{ run.action.book.title }}</h3>
      <p>借阅编号：{{ run.action.loan.id }}</p>
      <p>副本条码：{{ run.action.loan.barcode || '未登记' }}</p>
      <p>借出时间：{{ formatLoanTime(run.action.loan.borrowed_at) }}</p>
      <p>应还时间：{{ formatLoanTime(run.action.loan.due_at) }}</p>
      <p>{{ run.action.message }}</p>
      <p class="muted">确认有效期10分钟；提交时重新检查记录归属和实际状态。</p>
      <div class="borrow-controls">
        <el-button type="primary" :disabled="busy" @click="decide(true)"
          >确认提交归还申请</el-button
        >
        <el-button :disabled="busy" @click="decide(false)">取消本次操作</el-button>
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
      <h3 v-else-if="run.status === 'return_pending'">归还申请已提交 · 待管理员确认归还</h3>
      <h3 v-else-if="run.status === 'returned'">管理员已确认归还</h3>
      <p>{{ run.message }}</p>
      <p v-if="run.receipt?.loan_id">申请编号：{{ run.receipt.loan_id }}</p>
      <router-link v-if="['pending', 'return_pending', 'returned'].includes(run.status)" to="/loans"
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
.task-types {
  margin-top: 18px;
  max-width: 100%;
}
.loan-card .el-button {
  margin-top: 12px;
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
