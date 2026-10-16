<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getBookApi, getBooksApi } from '@/bookApi.js'
import { createLoanApi } from '@/loanApi.js'
import { canRequestLoan } from '@/utils/library.js'

const books = ref([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const loadFailed = ref(false)
const filters = reactive({ keyword: '', category: '' })
const query = reactive({ keyword: '', category: '' })
const busyId = ref(null)
const detailVisible = ref(false)
const detail = ref(null)
const detailLoading = ref(false)
const detailFailed = ref(false)
const detailId = ref(null)
let loadSequence = 0
let detailSequence = 0

async function fetchBooks() {
  const sequence = ++loadSequence
  loading.value = true
  loadFailed.value = false
  try {
    const data = await getBooksApi({ page: page.value, page_size: 12, ...query })
    if (sequence !== loadSequence) return
    books.value = data.items
    total.value = data.total
  } catch {
    if (sequence === loadSequence) loadFailed.value = true
  } finally {
    if (sequence === loadSequence) loading.value = false
  }
}

function searchBooks() {
  Object.assign(query, { keyword: filters.keyword.trim(), category: filters.category.trim() })
  page.value = 1
  fetchBooks()
}

async function openDetails(id) {
  const sequence = ++detailSequence
  detailId.value = id
  detail.value = null
  detailVisible.value = true
  detailLoading.value = true
  detailFailed.value = false
  try {
    const data = await getBookApi(id)
    if (sequence === detailSequence) detail.value = data
  } catch {
    if (sequence === detailSequence) detailFailed.value = true
  } finally {
    if (sequence === detailSequence) detailLoading.value = false
  }
}

async function requestLoan(book) {
  if (busyId.value || !canRequestLoan(book)) return
  busyId.value = book.id
  try {
    try {
      await ElMessageBox.confirm(
        `申请借阅《${book.title}》？申请不占用库存，请等待管理员确认借出。`,
        '申请借阅',
        { confirmButtonText: '提交申请', cancelButtonText: '取消' }
      )
    } catch {
      return
    }
    await createLoanApi(book.id)
    ElMessage.success('申请已提交，可在“我的借阅”查看进度')
    detailVisible.value = false
    await fetchBooks()
  } catch {
    // 请求层统一提示业务错误，保留列表供读者重试。
  } finally {
    busyId.value = null
  }
}

onMounted(fetchBooks)
</script>

<template>
  <div class="books-page">
    <section class="library-intro">
      <div>
        <span>LIBRARY COLLECTION</span>
        <h2>让下一本好书，走进你的生活</h2>
        <p>检索馆藏图书，在线提交借阅申请，管理员确认后领取实体书。</p>
      </div>
      <router-link to="/loans"><el-button plain>查看我的借阅</el-button></router-link>
    </section>

    <el-alert
      title="每人最多借阅 5 册，借期 30 天"
      description="申请不占用库存，管理员确认借出时分配副本。归还时请先提交申请，再由管理员确认收到图书。"
      type="info"
      :closable="false"
      show-icon
    />

    <form class="toolbar surface" @submit.prevent="searchBooks">
      <el-input
        v-model="filters.keyword"
        clearable
        placeholder="搜索书名、作者或 ISBN"
        aria-label="搜索书名、作者或 ISBN"
        @clear="searchBooks"
      />
      <el-input
        v-model="filters.category"
        clearable
        placeholder="分类（精确匹配）"
        aria-label="图书分类"
        @clear="searchBooks"
      />
      <el-button type="primary" native-type="submit" :loading="loading">搜索</el-button>
      <el-button :disabled="loading" @click="fetchBooks">刷新</el-button>
    </form>

    <el-alert
      v-if="loadFailed"
      title="图书列表加载失败，请点击刷新重试。"
      type="error"
      :closable="false"
    />
    <section v-loading="loading" class="collection">
      <div v-if="books.length" class="book-grid">
        <article v-for="book in books" :key="book.id" class="book-card surface">
          <div class="book-spine">
            <span>{{ book.category }}</span
            ><strong>{{ book.title }}</strong
            ><small>{{ book.author }}</small>
          </div>
          <div class="book-content">
            <h3>{{ book.title }}</h3>
            <p class="author">{{ book.author }} · {{ book.publisher || '出版社未提供' }}</p>
            <p class="description">
              {{ book.description || '暂无图书简介，可点击详情查看馆藏信息。' }}
            </p>
            <div class="stock">
              <el-tag :type="book.available_copies > 0 ? 'success' : 'info'" size="small"
                >可借 {{ book.available_copies }} 册</el-tag
              ><small>馆藏 {{ book.total_copies }} 册</small>
            </div>
            <div class="actions">
              <el-button @click="openDetails(book.id)">详情</el-button>
              <el-button
                type="primary"
                :disabled="Boolean(busyId) || !canRequestLoan(book)"
                :loading="busyId === book.id"
                @click="requestLoan(book)"
                >{{ book.available_copies > 0 ? '申请借阅' : '暂无可借副本' }}</el-button
              >
            </div>
          </div>
        </article>
      </div>
      <el-empty
        v-else-if="!loading && !loadFailed"
        description="没有找到匹配的图书，请调整关键词或分类"
        class="surface"
      />
    </section>
    <div class="pagination surface">
      <span>共 {{ total }} 条书目</span
      ><el-pagination
        v-model:current-page="page"
        :page-size="12"
        :total="total"
        layout="prev, pager, next"
        :disabled="loading"
        @current-change="fetchBooks"
      />
    </div>

    <el-dialog v-model="detailVisible" title="图书详情" width="min(640px, 94vw)">
      <div v-loading="detailLoading" class="detail-panel">
        <el-alert v-if="detailFailed" title="详情加载失败" type="error" :closable="false" />
        <el-button v-if="detailFailed" @click="openDetails(detailId)">重新加载</el-button>
        <template v-if="detail">
          <h3>{{ detail.title }}</h3>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="作者">{{ detail.author }}</el-descriptions-item>
            <el-descriptions-item label="ISBN">{{ detail.isbn || '未提供' }}</el-descriptions-item>
            <el-descriptions-item label="出版社"
              >{{ detail.publisher || '未提供' }}
              {{
                detail.publication_year ? `· ${detail.publication_year} 年` : ''
              }}</el-descriptions-item
            >
            <el-descriptions-item label="分类">{{ detail.category }}</el-descriptions-item>
            <el-descriptions-item label="馆藏"
              >可借 {{ detail.available_copies }} / 共
              {{ detail.total_copies }} 册</el-descriptions-item
            >
          </el-descriptions>
          <p class="full-description">{{ detail.description || '暂无简介' }}</p>
        </template>
      </div>
      <template #footer
        ><el-button @click="detailVisible = false">关闭</el-button
        ><el-button
          v-if="detail"
          type="primary"
          :disabled="Boolean(busyId) || !canRequestLoan(detail)"
          :loading="busyId === detail.id"
          @click="requestLoan(detail)"
          >{{ canRequestLoan(detail) ? '申请借阅' : '暂无可借副本' }}</el-button
        ></template
      >
    </el-dialog>
  </div>
</template>

<style scoped>
.books-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.library-intro {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 28px 30px;
  border-radius: 17px;
  color: white;
  background: var(--navy-900);
}
.library-intro > div > span {
  color: #e5be78;
  font-size: 9px;
  letter-spacing: 1.6px;
}
.library-intro h2 {
  margin: 9px 0;
  color: white;
  font-size: 25px;
}
.library-intro p {
  color: #c5d0d8;
  font-size: 12px;
  line-height: 1.7;
}
.toolbar {
  display: flex;
  gap: 12px;
  padding: 14px;
}
.toolbar > .el-input:first-child {
  flex: 1;
}
.toolbar > .el-input:nth-child(2) {
  max-width: 190px;
}
.collection {
  min-height: 260px;
}
.book-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
}
.book-card {
  overflow: hidden;
}
.book-spine {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 10px;
  min-height: 142px;
  padding: 22px;
  border-left: 9px solid #c3d7c9;
  color: #2f5751;
  background: #eaf0e7;
}
.book-card:nth-child(3n + 2) .book-spine {
  background: #f3ead8;
  border-color: #e1c994;
  color: #795f35;
}
.book-card:nth-child(3n + 3) .book-spine {
  background: #e5ecf1;
  border-color: #b2c9d9;
  color: #3f6076;
}
.book-spine span {
  font-size: 10px;
}
.book-spine strong {
  font-family: Georgia, 'Noto Serif SC', serif;
  font-size: 21px;
  overflow-wrap: anywhere;
}
.book-spine small {
  font-size: 11px;
}
.book-content {
  padding: 20px;
}
.book-content h3 {
  font-size: 15px;
  color: var(--ink);
  overflow-wrap: anywhere;
}
.author {
  margin-top: 6px;
  color: #7a8994;
  font-size: 11px;
}
.description {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  height: 40px;
  overflow: hidden;
  margin: 14px 0;
  color: #7a8994;
  font-size: 12px;
  line-height: 1.7;
}
.stock,
.actions {
  display: flex;
  align-items: center;
  gap: 10px;
  justify-content: space-between;
}
.stock small {
  color: #889693;
  font-size: 11px;
}
.actions {
  margin-top: 18px;
}
.actions > .el-button:last-child {
  flex: 1;
}
.pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  padding: 14px 18px;
  color: #7a8994;
  font-size: 12px;
}
.detail-panel {
  min-height: 130px;
}
.detail-panel h3 {
  margin-bottom: 18px;
  color: var(--ink);
}
.full-description {
  margin-top: 18px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.8;
}
@media (max-width: 1100px) {
  .book-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 700px) {
  .library-intro {
    align-items: flex-start;
    flex-direction: column;
    padding: 24px;
  }
  .library-intro h2 {
    font-size: 21px;
  }
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
  .book-grid {
    grid-template-columns: 1fr;
  }
}
</style>
