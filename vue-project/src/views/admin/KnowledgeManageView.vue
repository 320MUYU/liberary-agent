<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import KnowledgeSearchPanel from '@/components/KnowledgeSearchPanel.vue'

import {
  deleteKnowledgeDocumentApi,
  disableKnowledgeDocumentApi,
  getKnowledgeDocumentsApi,
  getKnowledgeIndexStatusApi,
  publishKnowledgeDocumentApi,
  retryKnowledgeVersionApi,
  uploadKnowledgeDocumentApi,
  uploadKnowledgeVersionApi
} from '@/api/knowledgeApi'
import {
  canPublishVersion,
  canRetryVersion,
  DOCUMENT_STATUSES,
  latestVersion,
  safeKnowledgeError,
  shouldPollKnowledgeDocuments,
  validateKnowledgeUpload,
  VERSION_STATUSES
} from '@/utils/knowledge'

const documents = ref([])
const loading = ref(false)
const refreshing = ref(false)
const loadFailed = ref(false)
const keyword = ref('')
const statusFilter = ref('')
const busyKey = ref('')
const uploading = ref(false)
const audits = reactive({})
const isBusy = computed(() => Boolean(busyKey.value) || uploading.value)
let pollTimer
let active = true

const visibleDocuments = computed(() =>
  documents.value.filter(
    (document) =>
      document.status !== 'deleted' &&
      (!statusFilter.value || document.status === statusFilter.value) &&
      document.title.toLocaleLowerCase().includes(keyword.value.trim().toLocaleLowerCase())
  )
)
const publishedCount = computed(
  () => documents.value.filter((item) => item.status === 'published').length
)
const processingCount = computed(() =>
  documents.value.reduce(
    (count, document) =>
      count +
      document.versions.filter((version) => ['queued', 'indexing'].includes(version.status)).length,
    0
  )
)

async function fetchDocuments(quiet = false) {
  if (refreshing.value) return
  clearTimeout(pollTimer)
  refreshing.value = true
  if (!quiet) loading.value = true
  let succeeded = false
  try {
    const data = await getKnowledgeDocumentsApi()
    if (!active) return
    documents.value = data
    for (const key of Object.keys(audits)) delete audits[key]
    loadFailed.value = false
    succeeded = true
  } catch {
    if (active) loadFailed.value = true
    // 请求拦截器统一提示鉴权与服务错误；失败后暂停轮询，供用户手动重试。
  } finally {
    refreshing.value = false
    loading.value = false
    if (active && succeeded && shouldPollKnowledgeDocuments(documents.value)) {
      pollTimer = setTimeout(() => fetchDocuments(true), 3000)
    }
  }
}

async function runAction(key, operation, message) {
  if (isBusy.value) return
  busyKey.value = key
  try {
    await operation()
    ElMessage.success(message)
    await fetchDocuments(true)
  } catch {
    // 请求拦截器提供错误反馈，保留当前文档以便重试。
  } finally {
    busyKey.value = ''
  }
}

function publish(document, version) {
  if (!canPublishVersion(document, version)) return
  runAction(
    `publish-${version.id}`,
    () => publishKnowledgeDocumentApi(document.id, version.id),
    `已发布「${document.title}」第 ${version.version_number} 版`
  )
}

function disable(document) {
  runAction(
    `disable-${document.id}`,
    () => disableKnowledgeDocumentApi(document.id),
    '文档已停用，AI 将不再使用该文档'
  )
}

function retry(version) {
  runAction(`retry-${version.id}`, () => retryKnowledgeVersionApi(version.id), '已重新加入处理队列')
}

async function auditVersion(version) {
  if (isBusy.value) return
  busyKey.value = `audit-${version.id}`
  try {
    const data = await getKnowledgeIndexStatusApi(version.id)
    if (active) audits[version.id] = data
  } catch {
    // 保留已有文档，统一请求拦截器展示核验失败原因。
  } finally {
    busyKey.value = ''
  }
}

async function remove(document) {
  if (isBusy.value) return
  try {
    await ElMessageBox.confirm(
      `确定删除「${document.title}」及其全部版本吗？删除后将立即停止检索，且无法恢复。`,
      '删除知识文档',
      {
        type: 'warning',
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger'
      }
    )
  } catch {
    return
  }
  await runAction(
    `delete-${document.id}`,
    () => deleteKnowledgeDocumentApi(document.id),
    '文档已删除'
  )
}

const uploadVisible = ref(false)
const uploadTarget = ref(null)
const uploadResetKey = ref(0)
const uploadForm = reactive({ title: '', file: null })

function openUpload(document = null) {
  if (isBusy.value) return
  uploadTarget.value = document
  uploadForm.title = document?.title || ''
  uploadForm.file = null
  uploadResetKey.value += 1
  uploadVisible.value = true
}

function selectFile(event) {
  const file = event.target.files?.[0] || null
  if (!file) {
    uploadForm.file = null
    return
  }
  const error = validateKnowledgeUpload({ title: '', file }, false)
  if (error) {
    ElMessage.warning(error)
    event.target.value = ''
    uploadForm.file = null
    return
  }
  uploadForm.file = file
}

async function upload() {
  if (isBusy.value) return
  const error = validateKnowledgeUpload(uploadForm, !uploadTarget.value)
  if (error) {
    ElMessage.warning(error)
    return
  }
  uploading.value = true
  try {
    const data = { title: uploadForm.title, file: uploadForm.file }
    if (uploadTarget.value) {
      await uploadKnowledgeVersionApi(uploadTarget.value.id, data)
    } else {
      await uploadKnowledgeDocumentApi(data)
    }
    uploadVisible.value = false
    ElMessage.success('文件已上传，处理完成后请手动发布')
    await fetchDocuments(true)
  } catch {
    // 保留弹窗和文件选择，用户可在网络恢复后直接重试。
  } finally {
    uploading.value = false
  }
}

function fileName(name) {
  return (
    String(name || '')
      .split(/[\\/]/)
      .pop() || '未命名文件'
  )
}

onMounted(() => fetchDocuments())
onUnmounted(() => {
  active = false
  clearTimeout(pollTimer)
})
</script>

<template>
  <div class="knowledge-page">
    <section class="knowledge-intro">
      <div>
        <span>LIBRARY KNOWLEDGE</span>
        <h2>知识库管理</h2>
        <p>维护公开馆规与预约说明，让每一次知识问答都有可查阅的依据。</p>
      </div>
      <div class="intro-stats">
        <div>
          <strong>{{ publishedCount }}</strong
          ><span>已发布文档</span>
        </div>
        <div>
          <strong>{{ processingCount }}</strong
          ><span>处理中版本</span>
        </div>
      </div>
    </section>

    <el-alert
      title="仅上传适合公开查阅的资料"
      description="文档内容将发送至云端计算向量，候选片段可能用于模型重排和 AI 回答。请勿上传个人资料、内部文件或密钥。新版本处理完成后需手动发布，期间已发布版本继续可用。"
      type="info"
      :closable="false"
      show-icon
    />

    <KnowledgeSearchPanel />

    <section class="toolbar surface">
      <el-input v-model="keyword" clearable placeholder="搜索文档标题" aria-label="搜索文档标题" />
      <el-select v-model="statusFilter" aria-label="按文档状态筛选">
        <el-option label="全部状态" value="" />
        <el-option label="未发布" value="draft" />
        <el-option label="已发布" value="published" />
        <el-option label="已停用" value="disabled" />
      </el-select>
      <el-button :loading="refreshing" :disabled="isBusy" @click="fetchDocuments()">刷新</el-button>
      <el-button type="primary" :disabled="isBusy" @click="openUpload()">上传文档</el-button>
    </section>

    <el-alert
      v-if="loadFailed"
      title="文档列表加载失败，请点击刷新重试。"
      type="error"
      :closable="false"
    />

    <section class="table-card surface">
      <el-table
        v-loading="loading"
        :data="visibleDocuments"
        row-key="id"
        empty-text="暂无知识文档，请上传馆规或预约说明"
      >
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="version-panel">
              <h3>版本与处理进度</h3>
              <p class="version-caption">
                只有发布版本会用于回答；“可发布”表示索引完成，尚需管理员确认发布。
              </p>
              <div
                v-for="version in [...row.versions].reverse()"
                :key="version.id"
                class="version-row"
              >
                <div class="version-description">
                  <strong
                    >第 {{ version.version_number }} 版 ·
                    {{ fileName(version.original_name) }}</strong
                  >
                  <div class="version-meta">
                    <el-tag :type="VERSION_STATUSES[version.status]?.type || 'info'" size="small">
                      {{ VERSION_STATUSES[version.status]?.label || '状态未知' }}
                    </el-tag>
                    <el-tag
                      v-if="row.status === 'published' && row.active_version_id === version.id"
                      type="success"
                      size="small"
                      effect="dark"
                      >当前发布</el-tag
                    >
                    <span>{{ version.chunk_count }} 个知识片段</span>
                  </div>
                  <p v-if="version.status === 'failed'" class="version-error">
                    {{ safeKnowledgeError(version.error_message) }}
                  </p>
                  <div v-if="audits[version.id]" class="index-audit">
                    <el-tag
                      :type="audits[version.id].status === 'consistent' ? 'success' : 'warning'"
                      size="small"
                    >
                      {{
                        {
                          consistent: '入库核验一致',
                          mismatch: '入库记录不一致',
                          in_progress: '处理中，稍后再核验'
                        }[audits[version.id].status]
                      }}
                    </el-tag>
                    <p>
                      正文 {{ audits[version.id].sql_count }} 段 · Chroma
                      {{ audits[version.id].vector_count }} 条 · 缺少
                      {{ audits[version.id].missing_count }} 条 · 多余
                      {{ audits[version.id].extra_count }} 条
                    </p>
                    <small>向量集合：{{ audits[version.id].collection }}</small>
                    <p v-if="!audits[version.id].profile_matches_current" class="version-error">
                      此版本使用旧向量模型配置，当前问答不会检索它，请上传新版本重新索引。
                    </p>
                    <p v-if="audits[version.id].status === 'mismatch'" class="version-error">
                      请检查索引服务。失败版本可重新处理；就绪版本可上传新版本重建。
                    </p>
                  </div>
                </div>
                <div class="version-actions">
                  <el-button
                    size="small"
                    :disabled="isBusy"
                    :loading="busyKey === `audit-${version.id}`"
                    @click="auditVersion(version)"
                    >核验入库</el-button
                  >
                  <el-button
                    v-if="canRetryVersion(version)"
                    size="small"
                    :disabled="isBusy"
                    :loading="busyKey === `retry-${version.id}`"
                    @click="retry(version)"
                    >重新处理</el-button
                  >
                  <el-button
                    v-if="canPublishVersion(row, version)"
                    size="small"
                    type="primary"
                    :disabled="isBusy"
                    :loading="busyKey === `publish-${version.id}`"
                    @click="publish(row, version)"
                    >发布此版本</el-button
                  >
                </div>
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="文档" min-width="190">
          <template #default="{ row }">
            <div class="document-cell">
              <strong>{{ row.title }}</strong
              ><small>{{ row.versions.length }} 个版本 · 展开查看详情</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="发布状态" width="110">
          <template #default="{ row }"
            ><el-tag :type="DOCUMENT_STATUSES[row.status]?.type || 'info'" size="small">{{
              DOCUMENT_STATUSES[row.status]?.label || '状态未知'
            }}</el-tag></template
          >
        </el-table-column>
        <el-table-column label="最新版本" min-width="145">
          <template #default="{ row }">
            <div v-if="latestVersion(row)" class="latest-version">
              <span>第 {{ latestVersion(row).version_number }} 版</span>
              <el-tag
                :type="VERSION_STATUSES[latestVersion(row).status]?.type || 'info'"
                size="small"
                >{{ VERSION_STATUSES[latestVersion(row).status]?.label || '状态未知' }}</el-tag
              >
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="310" align="right">
          <template #default="{ row }">
            <div class="document-actions">
              <el-button size="small" :disabled="isBusy" @click="openUpload(row)"
                >上传新版本</el-button
              >
              <el-button
                v-if="canPublishVersion(row, latestVersion(row))"
                size="small"
                type="primary"
                :disabled="isBusy"
                :loading="busyKey === `publish-${latestVersion(row).id}`"
                @click="publish(row, latestVersion(row))"
                >发布</el-button
              >
              <el-button
                v-if="row.status === 'published'"
                size="small"
                type="warning"
                plain
                :disabled="isBusy"
                :loading="busyKey === `disable-${row.id}`"
                @click="disable(row)"
                >停用</el-button
              >
              <el-button
                size="small"
                type="danger"
                text
                :disabled="isBusy"
                :loading="busyKey === `delete-${row.id}`"
                @click="remove(row)"
                >删除</el-button
              >
            </div>
          </template>
        </el-table-column>
      </el-table>
      <div class="table-footer">
        共 {{ visibleDocuments.length }} 篇文档<span v-if="processingCount"
          >处理进度每 3 秒自动更新</span
        >
      </div>
    </section>

    <el-dialog
      v-model="uploadVisible"
      :title="uploadTarget ? '上传文档新版本' : '上传知识文档'"
      width="min(560px, 94vw)"
      :close-on-click-modal="!uploading"
      :close-on-press-escape="!uploading"
      :show-close="!uploading"
    >
      <el-form label-position="top" @submit.prevent="upload">
        <el-form-item label="文档标题" required>
          <el-input
            v-model="uploadForm.title"
            :readonly="Boolean(uploadTarget)"
            :disabled="uploading"
            maxlength="200"
            show-word-limit
            placeholder="例如：图书馆学习空间预约说明"
          />
        </el-form-item>
        <el-form-item label="选择文件" required>
          <input
            :key="uploadResetKey"
            class="file-picker"
            type="file"
            accept=".txt,.md,.docx,.pdf"
            :disabled="uploading"
            aria-label="选择知识文档"
            @change="selectFile"
          />
          <p class="file-hint">
            支持 TXT、MD、DOCX 和有文字层的 PDF，单文件最多 10 MB。扫描件请先进行文字识别。
          </p>
        </el-form-item>
        <el-alert
          v-if="uploadTarget"
          title="新版本准备期间，当前已发布版本继续提供服务。"
          type="info"
          :closable="false"
        />
      </el-form>
      <template #footer>
        <el-button :disabled="uploading" @click="uploadVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploading" :disabled="!uploadForm.file" @click="upload"
          >上传并处理</el-button
        >
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.index-audit {
  margin-top: 10px;
  font-size: 13px;
  overflow-wrap: anywhere;
}
.index-audit p {
  margin: 6px 0;
}
.knowledge-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.knowledge-intro {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 24px;
  padding: 26px 30px;
  color: white;
  background: var(--navy-900);
  border-radius: 17px;
}
.knowledge-intro > div > span {
  color: #e5be78;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 1.6px;
}
.knowledge-intro h2 {
  margin: 8px 0;
  color: white;
  font-size: 25px;
}
.knowledge-intro p {
  color: #c5d0d8;
  font-size: 12px;
  line-height: 1.7;
}
.intro-stats {
  display: flex;
  gap: 30px;
  text-align: center;
  flex-shrink: 0;
}
.intro-stats strong,
.intro-stats span {
  display: block;
}
.intro-stats strong {
  color: #f0ca87;
  font-size: 27px;
}
.intro-stats span {
  margin-top: 4px;
  color: #c5d0d8;
  font-size: 11px;
}
.toolbar {
  display: flex;
  gap: 12px;
  padding: 14px;
}
.toolbar > .el-input {
  max-width: 330px;
  margin-right: auto;
}
.toolbar > .el-select {
  width: 145px;
}
.table-card {
  padding: 4px 4px 14px;
  overflow: hidden;
}
.document-cell strong,
.document-cell small {
  display: block;
}
.document-cell strong {
  color: var(--ink);
  font-size: 13px;
  overflow-wrap: anywhere;
}
.document-cell small {
  margin-top: 4px;
  color: #889693;
  font-size: 11px;
}
.latest-version,
.document-actions,
.version-meta,
.version-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.document-actions {
  justify-content: flex-end;
}
.document-actions .el-button + .el-button,
.version-actions .el-button + .el-button {
  margin-left: 0;
}
.table-footer {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  padding: 18px 16px 2px;
  font-size: 11px;
  color: #7a8994;
}
.version-panel {
  padding: 12px 24px 16px;
  background: #fbfaf6;
}
.version-panel h3 {
  color: var(--ink);
  font-size: 14px;
}
.version-caption {
  margin: 6px 0 10px;
  color: #7a8994;
  font-size: 11px;
}
.version-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 15px 0;
  border-bottom: 1px solid var(--line);
}
.version-row:last-child {
  border-bottom: 0;
}
.version-description {
  min-width: 0;
}
.version-description > strong {
  font-size: 12px;
  overflow-wrap: anywhere;
}
.version-meta {
  margin-top: 8px;
  font-size: 11px;
  color: #7a8994;
}
.version-error {
  margin-top: 8px;
  color: #b54b42;
  font-size: 12px;
  overflow-wrap: anywhere;
}
.version-actions {
  flex-shrink: 0;
}
.file-picker {
  width: 100%;
  padding: 14px;
  border: 1px dashed #c9c8bf;
  border-radius: 8px;
  background: #fbfaf6;
}
.file-hint {
  margin-top: 8px;
  color: #7a8994;
  font-size: 12px;
  line-height: 1.6;
}
.knowledge-page :deep(.el-alert__description) {
  line-height: 1.7;
}
.knowledge-page :deep(.el-table th.el-table__cell) {
  background: #f6f7f4;
  color: #517271;
}
.knowledge-page :deep(.el-table) {
  font-size: 12px;
}
@media (max-width: 800px) {
  .knowledge-intro {
    flex-direction: column;
    align-items: flex-start;
    padding: 24px;
  }
  .toolbar {
    flex-wrap: wrap;
  }
  .toolbar > .el-input {
    width: 100%;
    max-width: none;
  }
  .toolbar > .el-select {
    flex: 1;
    min-width: 110px;
  }
  .version-row {
    flex-direction: column;
    align-items: flex-start;
  }
  .version-panel {
    padding: 12px;
  }
}
</style>
