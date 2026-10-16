<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  createBookApi,
  createBookCopyApi,
  getAdminBooksApi,
  getBookCopiesApi,
  updateBookApi,
  updateBookCopyApi
} from '@/bookApi.js'
import { COPY_STATUSES, copyAvailability, toBookPayload } from '@/utils/library.js'

const books = ref([])
const page = ref(1)
const total = ref(0)
const filters = reactive({ keyword: '', category: '', is_active: '' })
const query = reactive({ keyword: '', category: '', is_active: undefined })
const loading = ref(false)
const loadFailed = ref(false)
const busyKey = ref('')
const saving = ref(false)
const isBusy = computed(() => saving.value || Boolean(busyKey.value))
let sequence = 0

async function fetchBooks() {
  const current = ++sequence
  loading.value = true
  loadFailed.value = false
  try {
    const data = await getAdminBooksApi({ page: page.value, page_size: 10, ...query })
    if (current !== sequence) return
    books.value = data.items
    total.value = data.total
  } catch {
    if (current === sequence) loadFailed.value = true
  } finally {
    if (current === sequence) loading.value = false
  }
}

function searchBooks() {
  Object.assign(query, {
    keyword: filters.keyword.trim(),
    category: filters.category.trim(),
    is_active: filters.is_active === '' ? undefined : filters.is_active
  })
  page.value = 1
  fetchBooks()
}

const bookVisible = ref(false)
const editingBookId = ref(null)
const bookFormRef = ref(null)
const emptyBook = () => ({
  title: '',
  author: '',
  isbn: '',
  publisher: '',
  publication_year: undefined,
  category: '未分类',
  description: '',
  cover: '',
  is_active: true
})
const bookForm = reactive(emptyBook())
const bookRules = {
  title: [{ required: true, whitespace: true, message: '请输入书名', trigger: 'blur' }],
  author: [{ required: true, whitespace: true, message: '请输入作者', trigger: 'blur' }],
  category: [{ required: true, whitespace: true, message: '请输入分类', trigger: 'blur' }]
}

function openBook(book = null) {
  if (isBusy.value) return
  editingBookId.value = book?.id || null
  Object.assign(bookForm, emptyBook(), book ? toBookPayload(book) : {})
  bookVisible.value = true
  bookFormRef.value?.clearValidate()
}

async function saveBook() {
  if (isBusy.value) return
  saving.value = true
  try {
    if (!(await bookFormRef.value?.validate().catch(() => false))) return
    const payload = toBookPayload(bookForm)
    if (editingBookId.value) await updateBookApi(editingBookId.value, payload)
    else await createBookApi(payload)
    bookVisible.value = false
    ElMessage.success(editingBookId.value ? '书目信息已更新' : '书目已创建，请添加馆藏副本')
    await fetchBooks()
  } catch {
    /* 请求层提示校验错误，保留表单。 */
  } finally {
    saving.value = false
  }
}

async function toggleBook(book) {
  if (isBusy.value) return
  busyKey.value = `toggle-${book.id}`
  try {
    await updateBookApi(book.id, { ...toBookPayload(book), is_active: !book.is_active })
    ElMessage.success(book.is_active ? '书目已下架，已有借阅记录保留' : '书目已上架')
    await fetchBooks()
  } catch {
    /* 请求层已提示错误。 */
  } finally {
    busyKey.value = ''
  }
}

const copiesVisible = ref(false)
const copyBook = ref(null)
const copies = ref([])
const copyPage = ref(1)
const copyTotal = ref(0)
const copiesLoading = ref(false)
const copiesFailed = ref(false)
let copiesSequence = 0

async function fetchCopies() {
  if (!copyBook.value) return
  const current = ++copiesSequence
  const bookId = copyBook.value.id
  copiesLoading.value = true
  copiesFailed.value = false
  try {
    const data = await getBookCopiesApi(bookId, { page: copyPage.value, page_size: 10 })
    if (current !== copiesSequence) return
    copies.value = data.items
    copyTotal.value = data.total
  } catch {
    if (current === copiesSequence) copiesFailed.value = true
  } finally {
    if (current === copiesSequence) copiesLoading.value = false
  }
}

function openCopies(book) {
  if (isBusy.value) return
  copyBook.value = book
  copies.value = []
  copyTotal.value = 0
  copyPage.value = 1
  copiesVisible.value = true
  fetchCopies()
}

const copyVisible = ref(false)
const editingCopy = ref(null)
const copyFormRef = ref(null)
const copyForm = reactive({ barcode: '', location: '', status: 'available' })
const copyRules = {
  barcode: [{ required: true, whitespace: true, message: '请输入馆藏条码', trigger: 'blur' }],
  location: [{ required: true, whitespace: true, message: '请输入馆藏位置', trigger: 'blur' }]
}

function openCopy(copy = null) {
  if (isBusy.value || copy?.is_on_loan) return
  editingCopy.value = copy
  Object.assign(copyForm, {
    barcode: copy?.barcode || '',
    location: copy?.location || '',
    status: copy?.status || 'available'
  })
  copyVisible.value = true
  copyFormRef.value?.clearValidate()
}

async function saveCopy() {
  if (isBusy.value) return
  saving.value = true
  try {
    if (!(await copyFormRef.value?.validate().catch(() => false))) return
    const payload = {
      barcode: copyForm.barcode.trim(),
      location: copyForm.location.trim(),
      status: copyForm.status
    }
    if (editingCopy.value) await updateBookCopyApi(editingCopy.value.id, payload)
    else await createBookCopyApi({ ...payload, book_id: copyBook.value.id })
    copyVisible.value = false
    ElMessage.success(editingCopy.value ? '馆藏副本已更新' : '馆藏副本已添加')
    await fetchCopies()
    await fetchBooks()
  } catch {
    /* 请求层已提示错误，保留表单。 */
  } finally {
    saving.value = false
  }
}

onMounted(fetchBooks)
</script>

<template>
  <div class="book-admin">
    <section class="page-heading">
      <div>
        <span>COLLECTION MANAGEMENT</span>
        <h2>书目与馆藏管理</h2>
        <p>维护书目信息与实体副本，库存根据可借副本和实际借阅情况自动计算。</p>
      </div>
      <el-button type="primary" :disabled="isBusy" @click="openBook()">新增书目</el-button>
    </section>
    <form class="toolbar surface" @submit.prevent="searchBooks">
      <el-input
        v-model="filters.keyword"
        clearable
        placeholder="搜索书名、作者或 ISBN"
        aria-label="搜索书目"
        @clear="searchBooks"
      />
      <el-input
        v-model="filters.category"
        clearable
        placeholder="分类（精确匹配）"
        aria-label="书目分类"
        @clear="searchBooks"
      />
      <el-select v-model="filters.is_active" aria-label="上架状态" @change="searchBooks"
        ><el-option label="全部状态" value="" /><el-option label="已上架" :value="true" /><el-option
          label="已下架"
          :value="false"
      /></el-select>
      <el-button type="primary" native-type="submit" :loading="loading">搜索</el-button
      ><el-button :disabled="loading || isBusy" @click="fetchBooks">刷新</el-button>
    </form>
    <el-alert
      v-if="loadFailed"
      title="书目加载失败，请点击刷新重试。"
      type="error"
      :closable="false"
    />
    <section class="table-card surface">
      <el-table v-loading="loading" :data="books" row-key="id" empty-text="暂无符合条件的书目">
        <el-table-column label="书目" min-width="220"
          ><template #default="{ row }"
            ><div class="book-cell">
              <strong>{{ row.title }}</strong
              ><small>{{ row.author }} · {{ row.isbn || '未提供 ISBN' }}</small>
            </div></template
          ></el-table-column
        >
        <el-table-column prop="category" label="分类" min-width="100" />
        <el-table-column label="上架状态" width="100"
          ><template #default="{ row }"
            ><el-tag :type="row.is_active ? 'success' : 'info'" size="small">{{
              row.is_active ? '已上架' : '已下架'
            }}</el-tag></template
          ></el-table-column
        >
        <el-table-column label="可借 / 馆藏" width="110"
          ><template #default="{ row }"
            >{{ row.available_copies }} / {{ row.total_copies }} 册</template
          ></el-table-column
        >
        <el-table-column label="操作" min-width="245" align="right"
          ><template #default="{ row }"
            ><div class="row-actions">
              <el-button size="small" :disabled="isBusy" @click="openBook(row)">编辑</el-button
              ><el-button size="small" :disabled="isBusy" @click="openCopies(row)"
                >馆藏副本</el-button
              ><el-button
                size="small"
                :type="row.is_active ? 'warning' : 'success'"
                plain
                :disabled="isBusy"
                :loading="busyKey === `toggle-${row.id}`"
                @click="toggleBook(row)"
                >{{ row.is_active ? '下架' : '上架' }}</el-button
              >
            </div></template
          ></el-table-column
        >
      </el-table>
      <div class="pagination">
        <span>共 {{ total }} 条书目</span
        ><el-pagination
          v-model:current-page="page"
          :page-size="10"
          :total="total"
          layout="prev, pager, next"
          :disabled="loading"
          @current-change="fetchBooks"
        />
      </div>
    </section>

    <el-dialog
      v-model="bookVisible"
      :title="editingBookId ? '编辑书目' : '新增书目'"
      width="min(700px, 94vw)"
      :close-on-click-modal="!saving"
      :close-on-press-escape="!saving"
      :show-close="!saving"
    >
      <el-form
        ref="bookFormRef"
        :model="bookForm"
        :rules="bookRules"
        label-position="top"
        :disabled="saving"
        @submit.prevent="saveBook"
      >
        <div class="form-row">
          <el-form-item label="书名" prop="title"
            ><el-input v-model="bookForm.title" maxlength="255" /></el-form-item
          ><el-form-item label="作者" prop="author"
            ><el-input v-model="bookForm.author" maxlength="255"
          /></el-form-item>
        </div>
        <div class="form-row">
          <el-form-item label="ISBN"
            ><el-input
              v-model="bookForm.isbn"
              maxlength="32"
              placeholder="有效的 ISBN-10 或 ISBN-13，可留空" /></el-form-item
          ><el-form-item label="分类" prop="category"
            ><el-input v-model="bookForm.category" maxlength="100"
          /></el-form-item>
        </div>
        <div class="form-row">
          <el-form-item label="出版社"
            ><el-input v-model="bookForm.publisher" maxlength="255" /></el-form-item
          ><el-form-item label="出版年份"
            ><el-input-number
              v-model="bookForm.publication_year"
              :min="1"
              :max="9999"
              :precision="0"
              :value-on-clear="null"
              class="full-width"
          /></el-form-item>
        </div>
        <el-form-item label="图书简介"
          ><el-input
            v-model="bookForm.description"
            type="textarea"
            :rows="4"
            maxlength="5000"
            show-word-limit /></el-form-item
        ><el-form-item label="封面地址"
          ><el-input
            v-model="bookForm.cover"
            maxlength="255"
            placeholder="可选，填写已有封面的地址" /></el-form-item
        ><el-form-item label="上架状态"
          ><el-switch v-model="bookForm.is_active" active-text="已上架" inactive-text="已下架"
        /></el-form-item>
      </el-form>
      <template #footer
        ><el-button :disabled="saving" @click="bookVisible = false">取消</el-button
        ><el-button type="primary" :loading="saving" @click="saveBook"
          >保存书目</el-button
        ></template
      >
    </el-dialog>

    <el-drawer
      v-model="copiesVisible"
      :title="`馆藏副本 · ${copyBook?.title || ''}`"
      size="min(820px, 96vw)"
      :close-on-click-modal="!saving"
      :close-on-press-escape="!saving"
      :show-close="!saving"
    >
      <el-alert
        title="正常馆藏且未借出的副本才可借出；归还申请期间仍显示借出中。"
        type="info"
        :closable="false"
      />
      <div class="drawer-toolbar">
        <span>共 {{ copyTotal }} 册</span
        ><el-button :disabled="copiesLoading || isBusy" @click="fetchCopies">刷新</el-button
        ><el-button type="primary" :disabled="isBusy" @click="openCopy()">新增副本</el-button>
      </div>
      <el-alert
        v-if="copiesFailed"
        title="馆藏副本加载失败，请点击刷新重试。"
        type="error"
        :closable="false"
      />
      <el-table
        v-loading="copiesLoading"
        :data="copies"
        row-key="id"
        empty-text="暂无实体副本，请添加馆藏"
      >
        <el-table-column prop="barcode" label="馆藏条码" min-width="125" /><el-table-column
          prop="location"
          label="位置"
          min-width="120"
        /><el-table-column label="馆藏状态" width="110"
          ><template #default="{ row }">{{
            COPY_STATUSES[row.status]?.label || '状态未知'
          }}</template></el-table-column
        ><el-table-column label="借阅情况" width="105"
          ><template #default="{ row }"
            ><el-tag :type="copyAvailability(row).type" size="small">{{
              copyAvailability(row).label
            }}</el-tag></template
          ></el-table-column
        ><el-table-column label="操作" width="80"
          ><template #default="{ row }"
            ><el-button
              size="small"
              :disabled="isBusy || row.is_on_loan"
              :title="row.is_on_loan ? '借出期间不可编辑，请先完成归还确认' : ''"
              @click="openCopy(row)"
              >编辑</el-button
            ></template
          ></el-table-column
        >
      </el-table>
      <div class="pagination">
        <span>副本按条码逐册管理</span
        ><el-pagination
          v-model:current-page="copyPage"
          :page-size="10"
          :total="copyTotal"
          layout="prev, pager, next"
          :disabled="copiesLoading"
          @current-change="fetchCopies"
        />
      </div>
    </el-drawer>

    <el-dialog
      v-model="copyVisible"
      :title="editingCopy ? '编辑馆藏副本' : '新增馆藏副本'"
      width="min(480px, 94vw)"
      :close-on-click-modal="!saving"
      :close-on-press-escape="!saving"
      :show-close="!saving"
    >
      <el-form
        ref="copyFormRef"
        :model="copyForm"
        :rules="copyRules"
        label-position="top"
        :disabled="saving"
        @submit.prevent="saveCopy"
        ><el-form-item label="馆藏条码" prop="barcode"
          ><el-input
            v-model="copyForm.barcode"
            maxlength="50"
            placeholder="全馆唯一的实体书条码" /></el-form-item
        ><el-form-item label="馆藏位置" prop="location"
          ><el-input
            v-model="copyForm.location"
            maxlength="100"
            placeholder="例如：二层 A 区 03 架" /></el-form-item
        ><el-form-item label="馆藏状态"
          ><el-select
            v-model="copyForm.status"
            :disabled="Boolean(editingCopy?.is_on_loan)"
            class="full-width"
            ><el-option
              v-for="(value, key) in COPY_STATUSES"
              :key="key"
              :label="value.label"
              :value="key" /></el-select></el-form-item
      ></el-form>
      <template #footer
        ><el-button :disabled="saving" @click="copyVisible = false">取消</el-button
        ><el-button type="primary" :loading="saving" @click="saveCopy"
          >保存副本</el-button
        ></template
      >
    </el-dialog>
  </div>
</template>

<style scoped>
.book-admin {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.page-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}
.page-heading span {
  color: var(--mint-dark);
  font-size: 9px;
  letter-spacing: 1.5px;
}
.page-heading h2 {
  margin-top: 8px;
  color: var(--ink);
  font-size: 25px;
}
.page-heading p {
  margin-top: 7px;
  color: #889693;
  font-size: 12px;
  line-height: 1.7;
}
.toolbar {
  display: flex;
  gap: 10px;
  padding: 14px;
}
.toolbar > .el-input:first-child {
  flex: 1;
}
.toolbar > .el-input:nth-child(2) {
  max-width: 170px;
}
.toolbar > .el-select {
  width: 130px;
}
.table-card {
  padding: 4px;
  overflow: hidden;
}
.book-cell strong,
.book-cell small {
  display: block;
}
.book-cell strong {
  color: var(--ink);
  font-size: 13px;
  overflow-wrap: anywhere;
}
.book-cell small {
  color: #889693;
  margin-top: 5px;
  font-size: 11px;
}
.row-actions {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 6px;
}
.row-actions .el-button + .el-button {
  margin: 0;
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
.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
}
.full-width {
  width: 100%;
}
.drawer-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 20px 0;
}
.drawer-toolbar > span {
  margin-right: auto;
  color: #7a8994;
  font-size: 12px;
}
.book-admin :deep(.el-table) {
  font-size: 12px;
}
.book-admin :deep(.el-table th.el-table__cell) {
  background: #f6f7f4;
  color: #517271;
}
@media (max-width: 800px) {
  .toolbar {
    flex-wrap: wrap;
  }
  .toolbar > .el-input:first-child {
    flex-basis: 100%;
  }
  .toolbar > .el-input:nth-child(2) {
    max-width: none;
    flex: 1;
  }
  .page-heading {
    flex-direction: column;
    align-items: flex-start;
  }
  .form-row {
    grid-template-columns: 1fr;
    gap: 0;
  }
}
</style>
