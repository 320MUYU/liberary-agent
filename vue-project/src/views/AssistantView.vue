<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { getUserInfo } from '@/auth'
import ConversationTaskCard from '@/components/ConversationTaskCard.vue'
import {
  createConversation,
  getConversation,
  sendConversationMessage,
  operateConversationTask
} from '@/api/conversationApi'

const userId = getUserInfo()?.id
const storageKey = `library-conversation-${userId}`
const pendingKey = `library-conversation-pending-${userId}`
const historyKey = `library-conversation-history-${userId}`
function stored(key, fallback) {
  try {
    return JSON.parse(sessionStorage.getItem(key)) || fallback
  } catch {
    return fallback
  }
}
const conversationId = ref(sessionStorage.getItem(storageKey) || '')
const state = ref({ turns: [], tasks: [] })
const input = ref('')
const hint = ref('auto')
const busy = ref(false)
const error = ref('')
const chatBody = ref(null)
const pending = ref(stored(pendingKey, null))
const history = ref(stored(historyKey, []))
const capabilities = [
  { value: 'auto', label: '自动识别' },
  { value: 'knowledge', label: '查馆规' },
  { value: 'library', label: '找书借还' },
  { value: 'space', label: '预约空间' },
  { value: 'chat', label: '聊一聊' }
]
const suggestions = [
  '研讨室的预约规则是什么？',
  '帮我找几本多智能体相关的书',
  '先查预约规则，再帮我预约研讨室'
]
const displayTurns = computed(() => {
  const turns = state.value.turns || []
  return pending.value && !turns.some((turn) => turn.request_id === pending.value.request_id)
    ? [...turns, { ...pending.value, status: 'processing', reply: null }]
    : turns
})
const activeTasks = computed(() =>
  state.value.tasks.filter((task) => !['completed', 'cancelled', 'expired'].includes(task.status))
)
let active = true
let generation = 0
onUnmounted(() => {
  active = false
  generation++
})
function scrollBottom() {
  nextTick(() => {
    if (chatBody.value) chatBody.value.scrollTop = chatBody.value.scrollHeight
  })
}
function clearPending() {
  pending.value = null
  sessionStorage.removeItem(pendingKey)
}
function apply(snapshot) {
  state.value = snapshot
  if (
    pending.value &&
    snapshot.turns.some(
      (turn) => turn.request_id === pending.value.request_id && turn.status === 'completed'
    )
  )
    clearPending()
  const title = snapshot.turns[0]?.text?.slice(0, 24) || '新对话'
  history.value = [
    { id: conversationId.value, title },
    ...history.value.filter((item) => item.id !== conversationId.value)
  ].slice(0, 20)
  sessionStorage.setItem(historyKey, JSON.stringify(history.value))
  scrollBottom()
}
async function perform(operation) {
  if (busy.value) return null
  busy.value = true
  error.value = ''
  const current = generation
  try {
    const snapshot = await operation()
    if (active && current === generation) {
      apply(snapshot)
      return snapshot
    }
  } catch (failure) {
    if (active && current === generation)
      error.value = failure.message || '请求未完成，请刷新后重试。'
  } finally {
    if (active && current === generation) busy.value = false
  }
  return null
}
async function ensureConversation() {
  if (!conversationId.value) {
    conversationId.value = crypto.randomUUID()
    sessionStorage.setItem(storageKey, conversationId.value)
  }
  await createConversation(conversationId.value)
}
async function progress(taskId) {
  for (let count = 0; count < 4; count++) {
    const task = state.value.tasks.find((item) => item.workflow_id === taskId)
    if (!active || !task || !['ready', 'planning'].includes(task.status)) break
    if (!(await perform(() => operateConversationTask(conversationId.value, taskId, 'retry'))))
      break
  }
}
async function retryPending() {
  if (busy.value || !pending.value) return
  const message = { ...pending.value }
  const snapshot = await perform(async () => {
    await ensureConversation()
    return sendConversationMessage(conversationId.value, message)
  })
  if (snapshot) {
    clearPending()
    await progress(
      snapshot.turns.find((turn) => turn.request_id === message.request_id)?.workflow_id
    )
  }
}
async function send(text = input.value) {
  if (busy.value) return
  const value = text.trim()
  if (!value) return
  if (value.length > 1000) {
    error.value = '每条需求不能超过1000字。'
    return
  }
  if (pending.value) {
    error.value = '上一条消息尚未恢复，请先重试或放弃重试。'
    return
  }
  pending.value = { request_id: crypto.randomUUID(), text: value, hint: hint.value }
  sessionStorage.setItem(pendingKey, JSON.stringify(pending.value))
  input.value = ''
  scrollBottom()
  await retryPending()
}
async function retryTurn(turn) {
  if (busy.value || pending.value) return
  pending.value = { request_id: turn.request_id, text: turn.text, hint: turn.hint || 'auto' }
  sessionStorage.setItem(pendingKey, JSON.stringify(pending.value))
  await retryPending()
}
async function refresh() {
  if (conversationId.value) await perform(() => getConversation(conversationId.value))
}
async function operateTask(taskId, operation, payload = {}) {
  const snapshot = await perform(() =>
    operation === 'view'
      ? getConversation(conversationId.value)
      : operateConversationTask(conversationId.value, taskId, operation, payload)
  )
  if (!snapshot) throw new Error(error.value || '请求尚未完成。')
  if (operation !== 'cancel' && operation !== 'view') await progress(taskId)
  return state.value
}
function newConversation() {
  if (busy.value) return
  generation++
  conversationId.value = ''
  state.value = { turns: [], tasks: [] }
  clearPending()
  input.value = ''
  error.value = ''
  hint.value = 'auto'
  sessionStorage.removeItem(storageKey)
}
async function openConversation(id) {
  if (busy.value || id === conversationId.value) return
  generation++
  clearPending()
  conversationId.value = id
  sessionStorage.setItem(storageKey, id)
  state.value = { turns: [], tasks: [] }
  await refresh()
}
function taskFor(turn) {
  return state.value.tasks.find((task) => task.workflow_id === turn.workflow_id)
}
function textOnly(turn) {
  const task = taskFor(turn)
  return task?.steps.length === 1 && task.steps[0].result?.status === 'answered'
}
onMounted(refresh)
</script>

<template>
  <div class="assistant-page">
    <section class="chat-panel surface" aria-label="阅见 AI 统一聊天">
      <header class="chat-header">
        <span class="ai-avatar"
          ><el-icon><MagicStick /></el-icon
        ></span>
        <div class="chat-title">
          <h2>阅见 AI</h2>
          <p><i></i> 图书、知识与空间，一起安排</p>
        </div>
        <el-button :disabled="busy" text @click="refresh">刷新</el-button>
        <el-button :disabled="busy" @click="newConversation">新对话</el-button>
      </header>
      <div ref="chatBody" class="chat-body" aria-live="polite" :aria-busy="busy">
        <div v-if="!displayTurns.length" class="welcome">
          <span class="welcome-mark"
            ><el-icon><Connection /></el-icon
          ></span>
          <span class="eyebrow">你的图书馆学习助手</span>
          <h3>这次学习，需要我帮你做些什么？</h3>
          <p>查馆规、找图书、查看借阅或预约空间。<br />直接说需求，也可以把几件事一起交给我。</p>
          <div class="suggestions">
            <button v-for="item in suggestions" :key="item" :disabled="busy" @click="send(item)">
              {{ item }}<span>↗</span>
            </button>
          </div>
        </div>
        <article v-for="turn in displayTurns" :key="turn.request_id" class="conversation-turn">
          <div class="user-message">
            <span>你</span>
            <p>{{ turn.text }}</p>
          </div>
          <div v-if="turn.reply || taskFor(turn)" class="assistant-message">
            <span class="assistant-label"
              ><el-icon><MagicStick /></el-icon> 阅见 AI</span
            >
            <p
              v-if="turn.reply && !textOnly(turn)"
              class="reply-text"
              :class="{ failed: turn.status === 'failed' }"
            >
              {{ turn.reply.content }}
            </p>
            <ConversationTaskCard
              v-if="taskFor(turn)"
              :task="taskFor(turn)"
              :busy="busy"
              :operate="operateTask"
            />
            <el-button
              v-if="turn.status === 'failed' && !pending"
              text
              :disabled="busy"
              @click="retryTurn(turn)"
              >重试本条消息</el-button
            >
          </div>
          <p v-else-if="turn.status === 'processing'" class="processing">
            {{ busy ? '正在理解需求并处理…' : '消息尚未完成，可刷新或重试恢复。' }}
          </p>
        </article>
        <div v-if="error" class="request-error" role="alert">{{ error }}</div>
        <div v-if="pending && !busy" class="recovery-controls">
          <el-button @click="retryPending">重试未完成消息</el-button
          ><el-button text @click="clearPending">放弃重试</el-button>
        </div>
        <p v-if="busy && displayTurns.length" class="processing" role="status">正在处理，请稍候…</p>
      </div>
      <footer class="composer">
        <div class="capabilities" aria-label="本轮能力偏好">
          <button
            v-for="item in capabilities"
            :key="item.value"
            :class="{ selected: hint === item.value }"
            :aria-pressed="hint === item.value"
            :disabled="busy"
            @click="hint = item.value"
          >
            {{ item.label }}
          </button>
        </div>
        <div class="input-row">
          <el-input
            v-model="input"
            type="textarea"
            :disabled="busy"
            :autosize="{ minRows: 2, maxRows: 5 }"
            maxlength="1000"
            resize="none"
            aria-label="聊天需求"
            placeholder="告诉我你的需求，或继续补充上一项任务…"
            @keydown.enter.exact.prevent="send()"
          /><button
            class="send-button"
            :disabled="busy || !input.trim()"
            aria-label="发送消息"
            @click="send()"
          >
            <el-icon><Promotion /></el-icon>
          </button>
        </div>
        <p class="composer-note">
          借阅、归还和预约需逐项确认，申请结果以管理员审核为准。<span
            >Enter 发送 · Shift + Enter 换行</span
          >
        </p>
      </footer>
    </section>
    <aside class="conversation-sidebar">
      <section class="surface sidebar-section">
        <span class="eyebrow">同一段对话，连续协作</span>
        <h3>从一个需求开始</h3>
        <p>系统自动选择需要的能力，追问和任务结果会留在当前聊天中。</p>
        <ul class="ability-list">
          <li>
            <span>01</span>
            <div>
              <strong>知识问答</strong>
              <p>查已发布馆规，附原文来源</p>
            </div>
          </li>
          <li>
            <span>02</span>
            <div>
              <strong>图书借还</strong>
              <p>找书、查库存、申请借阅与归还</p>
            </div>
          </li>
          <li>
            <span>03</span>
            <div>
              <strong>学习空间</strong>
              <p>查设施与时段，确认后申请预约</p>
            </div>
          </li>
        </ul>
      </section>
      <section class="surface sidebar-section">
        <h3>当前对话</h3>
        <p>
          {{
            activeTasks.length
              ? `${activeTasks.length} 项任务等待继续或确认`
              : '可以随时提出新的需求'
          }}
        </p>
        <p v-if="busy" class="live-status" role="status">正在处理本次请求</p>
        <label v-if="history.length" class="history-label"
          >最近对话<el-select
            :model-value="conversationId"
            :disabled="busy"
            placeholder="选择已有对话"
            aria-label="最近对话"
            @change="openConversation"
            ><el-option
              v-for="item in history"
              :key="item.id"
              :label="item.title"
              :value="item.id" /></el-select
        ></label>
      </section>
      <p class="sidebar-note">新对话会保留已有任务与申请。提交前会再次核验库存、权限和预约条件。</p>
    </aside>
  </div>
</template>

<style scoped>
.assistant-page {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: 22px;
  height: calc(100dvh - 150px);
  min-height: 590px;
}
.chat-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
}
.chat-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 18px 24px;
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
}
.ai-avatar {
  width: 40px;
  height: 40px;
  display: grid;
  place-items: center;
  background: var(--ink);
  color: #fff;
  border-radius: 12px;
  font-size: 21px;
}
.chat-title {
  flex: 1;
}
.chat-title h2 {
  color: var(--ink);
  font-size: 19px;
}
.chat-title p {
  color: var(--muted);
  font-size: 11px;
  margin-top: 4px;
}
.chat-title i {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--mint-dark);
  margin-right: 5px;
}
.chat-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 26px;
  scroll-behavior: smooth;
}
.welcome {
  max-width: 620px;
  margin: 5vh auto 24px;
}
.welcome-mark {
  display: grid;
  place-items: center;
  width: 55px;
  height: 55px;
  margin-bottom: 22px;
  border-radius: 18px;
  background: #e9f2ed;
  color: var(--mint-dark);
  font-size: 26px;
}
.eyebrow {
  color: var(--mint-dark);
  font-size: 11px;
  letter-spacing: 1px;
}
.welcome h3 {
  color: var(--ink);
  font-size: 27px;
  line-height: 1.5;
  margin: 10px 0 14px;
}
.welcome > p {
  color: var(--muted);
  line-height: 1.9;
}
.suggestions {
  display: grid;
  gap: 9px;
  margin-top: 28px;
}
.suggestions button {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 13px 16px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fcfcf9;
  text-align: left;
  font-size: 13px;
}
.suggestions button:hover {
  border-color: #a9c9b9;
  background: #f2f7f3;
}
.suggestions span {
  color: var(--mint-dark);
}
.conversation-turn {
  margin-bottom: 28px;
}
.user-message {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
  margin: 0 0 21px 12%;
}
.user-message > span {
  color: var(--muted);
  font-size: 11px;
}
.user-message p {
  padding: 12px 17px;
  border-radius: 15px 3px 15px 15px;
  background: #edf3ef;
  color: var(--ink);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-width: 100%;
  line-height: 1.8;
}
.assistant-label {
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--mint-dark);
  font-size: 12px;
  margin-bottom: 10px;
}
.reply-text {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.8;
}
.failed,
.request-error {
  color: #ad4a3b;
}
.request-error {
  border: 1px solid #efd6cd;
  border-radius: 10px;
  padding: 12px;
  background: #fff8f4;
  font-size: 13px;
}
.recovery-controls {
  margin-top: 10px;
}
.processing {
  color: var(--muted);
  font-size: 12px;
  padding: 12px 0;
}
.composer {
  flex-shrink: 0;
  padding: 14px 24px 16px;
  background: #fff;
  border-top: 1px solid var(--line);
}
.capabilities {
  display: flex;
  gap: 7px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.capabilities button {
  border: 1px solid transparent;
  border-radius: 7px;
  padding: 5px 10px;
  background: transparent;
  color: var(--muted);
  font-size: 12px;
}
.capabilities button.selected {
  color: var(--mint-dark);
  background: #edf5ef;
  border-color: #d5e5da;
}
.input-row {
  display: flex;
  align-items: flex-end;
  gap: 10px;
}
.input-row :deep(.el-textarea__inner) {
  box-shadow: 0 0 0 1px #e0e6df inset;
  border-radius: 12px;
  padding: 12px 14px;
  background: #fcfdfa;
}
.send-button {
  border: 0;
  width: 42px;
  height: 42px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 11px;
  background: var(--mint-dark);
  color: #fff;
  font-size: 20px;
}
.send-button:disabled {
  opacity: 0.4;
  cursor: default;
}
.composer-note {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 6px;
  margin-top: 9px;
  color: var(--muted);
  font-size: 10px;
}
.sidebar-section {
  padding: 24px;
  margin-bottom: 18px;
}
.sidebar-section h3 {
  color: var(--ink);
  font-size: 16px;
  margin: 10px 0;
}
.sidebar-section p,
.sidebar-note {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.9;
}
.ability-list {
  display: grid;
  gap: 22px;
  margin-top: 28px;
}
.ability-list li {
  display: flex;
  gap: 12px;
}
.ability-list li > span {
  color: #a2b6a9;
  font-size: 11px;
  line-height: 22px;
}
.ability-list strong {
  color: var(--text);
  font-size: 13px;
  font-weight: 500;
}
.history-label {
  display: grid;
  gap: 8px;
  margin-top: 20px;
  font-size: 12px;
  color: var(--muted);
}
.sidebar-note {
  padding: 0 15px;
}
.sidebar-section .live-status {
  color: var(--mint-dark);
}
@media (max-width: 1100px) {
  .assistant-page {
    grid-template-columns: 1fr;
  }
  .conversation-sidebar {
    display: none;
  }
}
@media (max-width: 600px) {
  .assistant-page {
    height: calc(100dvh - 126px);
    min-height: 500px;
  }
  .chat-header {
    padding: 14px;
    gap: 8px;
  }
  .chat-title p {
    max-width: 140px;
  }
  .chat-header :deep(.el-button) {
    padding: 8px;
    margin: 0;
  }
  .chat-body {
    padding: 18px 13px;
  }
  .composer {
    padding: 12px;
  }
  .welcome {
    margin-top: 10px;
  }
  .welcome h3 {
    font-size: 22px;
  }
  .composer-note span {
    display: none;
  }
  .capabilities {
    gap: 2px;
  }
  .capabilities button {
    padding: 5px 7px;
  }
}
</style>
