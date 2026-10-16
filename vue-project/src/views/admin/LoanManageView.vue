<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getBookCopiesApi } from '@/bookApi.js'
import { confirmBorrowApi, confirmReturnApi, getAdminLoansApi, rejectLoanApi } from '@/loanApi.js'
import { formatLoanTime, loanActions, LOAN_STATUSES } from '@/utils/library.js'

const items = ref([])
const total = ref(0)
const page = ref(1)
const filters = reactive({ keyword: '', status: '' })
const query = reactive({ keyword: '', status: undefined })
const loading = ref(false)
const loadFailed = ref(false)
const busyKey = ref('')
const borrowVisible = ref(false)
const rejectVisible = ref(false)
const actionsBlocked = computed(
  () => Boolean(busyKey.value) || borrowVisible.value || rejectVisible.value
)
let sequence = 0

async function fetchLoans() {
  const current = ++sequence
  loading.value = true
  loadFailed.value = false
  try {
    const data = await getAdminLoansApi({ page: page.value, page_size: 10, ...query })
    if (current !== sequence) return
    items.value = data.items
    total.value = data.total
  } catch {
    if (current === sequence) loadFailed.value = true
  } finally {
    if (current === sequence) loading.value = false
  }
}

function searchLoans() {
  Object.assign(query, { keyword: filters.keyword.trim(), status: filters.status || undefined })
  page.value = 1
  fetchLoans()
}

const detail = ref(null)
const detailVisible = ref(false)
function showDetail(item) {
  detail.value = item
  detailVisible.value = true
}

const borrowTarget = ref(null)
const assignMode = ref('auto')
const selectedCopy = ref(null)
const copyChoices = ref([])
const copyLoading = ref(false)
const copyFailed = ref(false)
const copyPage = ref(0)
const copyTotal = ref(0)
const hasMoreCopies = computed(() => copyPage.value * 100 < copyTotal.value)
let copySequence = 0

async function loadCopyChoices(reset = false) {
  if (!borrowTarget.value || (copyLoading.value && !reset)) return
  const current = ++copySequence
  const bookId = borrowTarget.value.book_id
  const nextPage = reset ? 1 : copyPage.value + 1
  copyLoading.value = true
  copyFailed.value = false
  try {
    const data = await getBookCopiesApi(bookId, { page: nextPage, page_size: 100 })
    if (current !== copySequence) return
    const available = data.items.filter((copy) => copy.status === 'available' && !copy.is_on_loan)
    copyChoices.value = reset ? available : [...copyChoices.value, ...available]
    copyPage.value = nextPage
    copyTotal.value = data.total
  } catch {
    if (current === copySequence) copyFailed.value = true
  } finally {
    if (current === copySequence) copyLoading.value = false
  }
}

function openBorrow(item) {
  if (actionsBlocked.value || !loanActions(item.status, 'admin').includes('confirm-borrow')) return
  borrowTarget.value = item
  assignMode.value = 'auto'
  selectedCopy.value = null
  copyChoices.value = []
  copyPage.value = 0
  copyTotal.value = 0
  borrowVisible.value = true
  loadCopyChoices(true)
}

async function confirmBorrow() {
  if (busyKey.value || !borrowTarget.value) return
  if (assignMode.value === 'manual' && !selectedCopy.value) {
    ElMessage.warning('请选择要借出的馆藏副本')
    return
  }
  busyKey.value = `borrow-${borrowTarget.value.id}`
  try {
    await confirmBorrowApi(
      borrowTarget.value.id,
      assignMode.value === 'manual' ? selectedCopy.value : undefined
    )
    borrowVisible.value = false
    ElMessage.success('已确认借出，借期为 30 天')
    await fetchLoans()
  } catch {
    /* 请求层提示副本已占用或读者超额等原因，可重新选择。 */
  } finally {
    busyKey.value = ''
  }
}

const rejectTarget = ref(null)
const rejectReason = ref('')
function openReject(item) {
  if (actionsBlocked.value || !loanActions(item.status, 'admin').includes('reject')) return
  rejectTarget.value = item
  rejectReason.value = ''
  rejectVisible.value = true
}

async function rejectLoan() {
  if (busyKey.value || !rejectTarget.value) return
  const reason = rejectReason.value.trim()
  if (!reason || [...reason].length > 500) {
    ElMessage.warning('请填写 1 至 500 字的拒绝原因')
    return
  }
  busyKey.value = `reject-${rejectTarget.value.id}`
  try {
    await rejectLoanApi(rejectTarget.value.id, reason)
    rejectVisible.value = false
    ElMessage.success('借阅申请已拒绝，读者可查看原因')
    await fetchLoans()
  } catch {
    /* 请求层提示错误，保留拒绝原因供重试。 */
  } finally {
    busyKey.value = ''
  }
}

async function confirmReturn(item) {
  if (actionsBlocked.value || !loanActions(item.status, 'admin').includes('confirm-return')) return
  busyKey.value = `return-${item.id}`
  try {
    try {
      await ElMessageBox.confirm(
        `请核对已收到《${item.book_title}》的实体书（条码：${item.barcode}）。确认后结束借阅，副本恢复可借。`,
        '确认归还',
        { confirmButtonText: '已收到，确认归还', cancelButtonText: '暂不确认', type: 'warning' }
      )
    } catch {
      return
    }
    await confirmReturnApi(item.id)
    ElMessage.success('已确认归还，副本已恢复可借')
    await fetchLoans()
  } catch {
    /* 请求层已提示错误。 */
  } finally {
    busyKey.value = ''
  }
}

onMounted(fetchLoans)
</script>

<template>
  <div class="loan-admin">
    <section class="page-heading">
      <span>BORROWING MANAGEMENT</span>
      <h2>借还审核</h2>
      <p>确认借出时分配实体副本，确认归还时核对并收回实体书。</p>
    </section>
    <el-alert
      title="每位读者最多借阅 5 册，借期 30 天。申请不占用库存，确认借出时再次校验副本与借阅额度。"
      type="info"
      :closable="false"
      show-icon
    />
    <form class="toolbar surface" @submit.prevent="searchLoans">
      <el-input
        v-model="filters.keyword"
        clearable
        placeholder="搜索读者姓名、账号或书名"
        aria-label="搜索借阅申请"
        @clear="searchLoans"
      /><el-select v-model="filters.status" aria-label="按借阅状态筛选" @change="searchLoans"
        ><el-option label="全部状态" value="" /><el-option
          v-for="(value, key) in LOAN_STATUSES"
          :key="key"
          :label="value.label"
          :value="key" /></el-select
      ><el-button type="primary" native-type="submit" :loading="loading">搜索</el-button
      ><el-button :disabled="loading || actionsBlocked" @click="fetchLoans">刷新</el-button>
    </form>
    <el-alert
      v-if="loadFailed"
      title="借阅记录加载失败，请点击刷新重试。"
      type="error"
      :closable="false"
    />
    <section class="table-card surface">
      <el-table v-loading="loading" :data="items" row-key="id" empty-text="暂无符合条件的借阅记录">
        <el-table-column label="图书 / 读者" min-width="220"
          ><template #default="{ row }"
            ><div class="loan-cell">
              <strong>{{ row.book_title }}</strong
              ><small
                >{{ row.reader_name || row.reader_username }} · {{ row.reader_username }} · #{{
                  row.id
                }}</small
              >
            </div></template
          ></el-table-column
        >
        <el-table-column label="状态" min-width="140"
          ><template #default="{ row }"
            ><div class="status-cell">
              <el-tag :type="LOAN_STATUSES[row.status]?.type || 'info'" size="small">{{
                LOAN_STATUSES[row.status]?.label || '状态未知'
              }}</el-tag
              ><el-tag v-if="row.is_overdue" type="danger" size="small">已逾期</el-tag>
            </div></template
          ></el-table-column
        >
        <el-table-column label="馆藏条码" min-width="120"
          ><template #default="{ row }">{{ row.barcode || '待分配' }}</template></el-table-column
        >
        <el-table-column label="应还时间" min-width="145"
          ><template #default="{ row }"
            ><span :class="{ overdue: row.is_overdue }">{{
              formatLoanTime(row.due_at)
            }}</span></template
          ></el-table-column
        >
        <el-table-column label="操作" min-width="250" align="right"
          ><template #default="{ row }"
            ><div class="row-actions">
              <el-button size="small" @click="showDetail(row)">详情</el-button
              ><el-button
                v-if="loanActions(row.status, 'admin').includes('confirm-borrow')"
                size="small"
                type="primary"
                :disabled="actionsBlocked"
                @click="openBorrow(row)"
                >确认借出</el-button
              ><el-button
                v-if="loanActions(row.status, 'admin').includes('reject')"
                size="small"
                type="danger"
                plain
                :disabled="actionsBlocked"
                @click="openReject(row)"
                >拒绝</el-button
              ><el-button
                v-if="loanActions(row.status, 'admin').includes('confirm-return')"
                size="small"
                type="success"
                :disabled="actionsBlocked"
                :loading="busyKey === `return-${row.id}`"
                @click="confirmReturn(row)"
                >确认归还</el-button
              >
            </div></template
          ></el-table-column
        >
      </el-table>
      <div class="pagination">
        <span>共 {{ total }} 条记录</span
        ><el-pagination
          v-model:current-page="page"
          :page-size="10"
          :total="total"
          layout="prev, pager, next"
          :disabled="loading"
          @current-change="fetchLoans"
        />
      </div>
    </section>

    <el-dialog
      v-model="borrowVisible"
      title="确认实体书借出"
      width="min(570px, 94vw)"
      :close-on-click-modal="!busyKey"
      :close-on-press-escape="!busyKey"
      :show-close="!busyKey"
    >
      <template v-if="borrowTarget"
        ><p class="dialog-caption">
          {{ borrowTarget.reader_name || borrowTarget.reader_username }} 申请借阅《{{
            borrowTarget.book_title
          }}》
        </p>
        <el-alert
          title="请在读者领取实体书时确认。确认后开始计算 30 天借期。"
          type="info"
          :closable="false"
        /><el-radio-group v-model="assignMode" :disabled="Boolean(busyKey)" class="assign-mode"
          ><el-radio value="auto">自动分配可借副本</el-radio
          ><el-radio value="manual">指定馆藏副本</el-radio></el-radio-group
        >
        <template v-if="assignMode === 'manual'"
          ><el-select
            v-model="selectedCopy"
            filterable
            clearable
            placeholder="按条码选择可借副本"
            aria-label="选择借出副本"
            :loading="copyLoading"
            :disabled="Boolean(busyKey)"
            class="full-width"
            ><el-option
              v-for="copy in copyChoices"
              :key="copy.id"
              :value="copy.id"
              :label="`${copy.barcode} · ${copy.location}`"
          /></el-select>
          <p class="copy-hint">仅显示正常馆藏且未被借出的副本，确认时将再次检查可用性。</p>
          <el-alert
            v-if="copyFailed"
            title="副本列表加载失败，可点击下方按钮重试。"
            type="error"
            :closable="false"
          /><el-button
            v-if="copyFailed"
            :loading="copyLoading"
            :disabled="Boolean(busyKey)"
            @click="loadCopyChoices(copyPage === 0)"
            >重试加载副本</el-button
          ><el-button
            v-else-if="hasMoreCopies"
            :loading="copyLoading"
            :disabled="Boolean(busyKey)"
            @click="loadCopyChoices()"
            >加载更多馆藏副本</el-button
          >
          <p v-if="!copyChoices.length && !copyLoading && !copyFailed" class="copy-hint">
            已加载的馆藏中暂无可借副本。可继续加载其他馆藏或稍后重试。
          </p></template
        >
      </template>
      <template #footer
        ><el-button :disabled="Boolean(busyKey)" @click="borrowVisible = false">取消</el-button
        ><el-button
          type="primary"
          :loading="Boolean(busyKey)"
          :disabled="assignMode === 'manual' && !selectedCopy"
          @click="confirmBorrow"
          >确认借出</el-button
        ></template
      >
    </el-dialog>

    <el-dialog
      v-model="rejectVisible"
      title="拒绝借阅申请"
      width="min(520px, 94vw)"
      :close-on-click-modal="!busyKey"
      :close-on-press-escape="!busyKey"
      :show-close="!busyKey"
      ><p class="dialog-caption">
        《{{ rejectTarget?.book_title }}》 ·
        {{ rejectTarget?.reader_name || rejectTarget?.reader_username }}
      </p>
      <el-input
        v-model="rejectReason"
        type="textarea"
        :rows="4"
        maxlength="500"
        show-word-limit
        placeholder="请填写拒绝原因，读者可以查看"
        aria-label="拒绝原因"
        :disabled="Boolean(busyKey)"
      /><template #footer
        ><el-button :disabled="Boolean(busyKey)" @click="rejectVisible = false">取消</el-button
        ><el-button
          type="danger"
          :disabled="!rejectReason.trim()"
          :loading="Boolean(busyKey)"
          @click="rejectLoan"
          >确认拒绝</el-button
        ></template
      ></el-dialog
    >

    <el-dialog v-model="detailVisible" title="借阅详情" width="min(640px, 94vw)"
      ><el-descriptions v-if="detail" :column="1" border
        ><el-descriptions-item label="图书">{{ detail.book_title }}</el-descriptions-item
        ><el-descriptions-item label="读者"
          >{{ detail.reader_name || detail.reader_username }}（{{
            detail.reader_username
          }}）</el-descriptions-item
        ><el-descriptions-item label="状态">{{
          LOAN_STATUSES[detail.status]?.label || '状态未知'
        }}</el-descriptions-item
        ><el-descriptions-item label="申请时间">{{
          formatLoanTime(detail.create_time)
        }}</el-descriptions-item
        ><el-descriptions-item label="馆藏条码">{{
          detail.barcode || '待分配'
        }}</el-descriptions-item
        ><el-descriptions-item label="馆藏位置">{{
          detail.location || '待分配'
        }}</el-descriptions-item
        ><el-descriptions-item label="借出时间">{{
          formatLoanTime(detail.borrowed_at)
        }}</el-descriptions-item
        ><el-descriptions-item label="应还时间">{{
          formatLoanTime(detail.due_at)
        }}</el-descriptions-item
        ><el-descriptions-item label="归还申请">{{
          formatLoanTime(detail.return_requested_at)
        }}</el-descriptions-item
        ><el-descriptions-item label="确认归还">{{
          formatLoanTime(detail.returned_at)
        }}</el-descriptions-item
        ><el-descriptions-item v-if="detail.reject_reason" label="拒绝原因">{{
          detail.reject_reason
        }}</el-descriptions-item></el-descriptions
      ></el-dialog
    >
  </div>
</template>

<style scoped>
.loan-admin {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.page-heading > span {
  color: var(--mint-dark);
  font-size: 9px;
  letter-spacing: 1.5px;
}
.page-heading h2 {
  color: var(--ink);
  font-size: 25px;
  margin-top: 8px;
}
.page-heading p {
  color: #889693;
  margin-top: 7px;
  font-size: 12px;
  line-height: 1.7;
}
.toolbar {
  display: flex;
  gap: 12px;
  padding: 14px;
}
.toolbar > .el-input {
  flex: 1;
}
.toolbar > .el-select {
  width: 160px;
}
.table-card {
  overflow: hidden;
  padding: 4px;
}
.loan-cell strong,
.loan-cell small {
  display: block;
}
.loan-cell strong {
  color: var(--ink);
  font-size: 13px;
  overflow-wrap: anywhere;
}
.loan-cell small {
  color: #889693;
  margin-top: 5px;
  font-size: 11px;
}
.row-actions,
.status-cell {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.row-actions {
  justify-content: flex-end;
}
.row-actions .el-button + .el-button {
  margin: 0;
}
.overdue {
  color: #b54b42;
}
.pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  padding: 16px;
  color: #7a8994;
  font-size: 12px;
}
.dialog-caption {
  margin-bottom: 16px;
  font-size: 14px;
  line-height: 1.7;
  overflow-wrap: anywhere;
}
.assign-mode {
  margin: 18px 0;
}
.full-width {
  width: 100%;
}
.copy-hint {
  margin: 12px 0;
  color: #7a8994;
  font-size: 12px;
  line-height: 1.7;
}
.loan-admin :deep(.el-table) {
  font-size: 12px;
}
.loan-admin :deep(.el-table th.el-table__cell) {
  background: #f6f7f4;
  color: #517271;
}
@media (max-width: 700px) {
  .toolbar {
    flex-wrap: wrap;
  }
  .toolbar > .el-input {
    flex-basis: 100%;
  }
  .toolbar > .el-select {
    flex: 1;
  }
  .assign-mode {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
