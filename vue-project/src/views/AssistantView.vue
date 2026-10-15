<script setup>
import { computed, nextTick, ref } from 'vue'
import { chatApi } from '@/aiApi'
import { getKnowledgeSourceApi } from '@/api/knowledgeApi'
import { buildChatHistory, retrievalLabel } from '@/utils/chatConversation'

const input = ref('')
const thinking = ref(false)
const chatBody = ref()
const errorMessage = ref('')
const mode = ref('chat')
const pendingRequest = ref(null)
const sourceDialog = ref(false)
const sourceLoading = ref(false)
const sourceContent = ref(null)
const sourceError = ref('')
const suggestions = computed(() =>
  mode.value === 'knowledge'
    ? ['学习空间的预约规则是什么？', '馆内可以携带食物吗？', '预约后应该如何取消？']
    : ['如何在系统中提交预约？', '如何挑选适合小组讨论的空间？', '怎样查看我的预约状态？']
)

function currentTime() {
  return new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function welcomeMessage() {
  return {
    role: 'assistant',
    text:
      mode.value === 'knowledge'
        ? '你好，知识库模式只根据管理员已发布的馆规与说明回答，并附上来源。没有依据时会明确说明。实时空闲和个人预约请前往业务页面查询。'
        : '你好，我是阅见 AI 空间助手，可以介绍系统流程并提供一般建议。馆规问题请切换“知识库问答”；实时空间、设施和预约状态请以系统页面为准。',
    time: currentTime(),
    localOnly: true
  }
}

const messages = ref([welcomeMessage()])
const lastResult = computed(() =>
  [...messages.value].reverse().find((message) => message.retrievalStatus)
)
const currentStatus = computed(() =>
  errorMessage.value
    ? '本次请求失败，可重试'
    : thinking.value
      ? mode.value === 'knowledge'
        ? '正在检索知识库并生成回答'
        : '正在生成回答'
      : retrievalLabel(lastResult.value?.retrievalStatus) || '等待发送问题'
)

function scrollBottom() {
  nextTick(() => {
    if (chatBody.value) chatBody.value.scrollTop = chatBody.value.scrollHeight
  })
}

async function send(text = input.value) {
  const value = text.trim()
  if (!value || thinking.value) return

  if (value.length > 4000) {
    errorMessage.value = '每条消息不能超过4000字。'
    return
  }
  const userMessage = { role: 'user', text: value, time: currentTime() }
  messages.value.push(userMessage)
  input.value = ''
  pendingRequest.value = {
    history: buildChatHistory(messages.value),
    mode: mode.value,
    userMessage
  }
  await submitPending()
}

async function submitPending() {
  if (thinking.value || !pendingRequest.value) return
  const request = pendingRequest.value
  request.userMessage.failed = false
  thinking.value = true
  errorMessage.value = ''
  scrollBottom()

  try {
    const reply = await chatApi(request.history, request.mode)
    messages.value.push({
      role: 'assistant',
      text: reply.content,
      time: currentTime(),
      sources: reply.sources || [],
      retrievalStatus: reply.retrieval_status || 'not_requested'
    })
    pendingRequest.value = null
  } catch (error) {
    request.userMessage.failed = true
    errorMessage.value =
      error.response?.data?.message || error.message || '本次回答生成失败，请稍后重试。'
  } finally {
    thinking.value = false
    scrollBottom()
  }
}

function resetConversation() {
  messages.value = [welcomeMessage()]
  input.value = ''
  errorMessage.value = ''
  pendingRequest.value = null
}

async function openSource(source) {
  sourceDialog.value = true
  sourceLoading.value = true
  sourceContent.value = null
  sourceError.value = ''
  try {
    // Fetch through the authenticated request client, never a public uploads URL.
    sourceContent.value = await getKnowledgeSourceApi(source.chunk_id)
  } catch (error) {
    sourceError.value = error.response?.data?.message || error.message || '来源已停用或暂时不可用。'
  } finally {
    sourceLoading.value = false
  }
}
</script>

<template>
  <div class="assistant-page">
    <section class="chat-panel surface">
      <header class="chat-header">
        <div class="ai-avatar">
          <el-icon><MagicStick /></el-icon><i></i>
        </div>
        <div>
          <h2>阅见 AI</h2>
          <p><span></span> LangChain · DeepSeek</p>
        </div>
        <el-select
          v-model="mode"
          class="mode-select"
          aria-label="问答模式"
          :disabled="thinking"
          @change="resetConversation"
        >
          <el-option label="普通聊天" value="chat" />
          <el-option label="知识库问答" value="knowledge" />
        </el-select>
        <button class="clear-chat" title="新建对话" :disabled="thinking" @click="resetConversation">
          <el-icon><EditPen /></el-icon>
        </button>
      </header>

      <div ref="chatBody" class="chat-body">
        <div class="day-divider"><span>今天</span></div>
        <div v-for="(message, index) in messages" :key="index" :class="['message', message.role]">
          <span v-if="message.role === 'assistant'" class="message-avatar"
            ><el-icon><MagicStick /></el-icon
          ></span>
          <div class="message-wrap">
            <div class="bubble">{{ message.text }}</div>
            <div v-if="message.retrievalStatus" class="retrieval-status">
              {{ retrievalLabel(message.retrievalStatus) }}
            </div>
            <div v-if="message.sources?.length" class="answer-sources">
              <button
                v-for="source in message.sources"
                :key="source.number"
                @click="openSource(source)"
              >
                [{{ source.number }}] {{ source.title }} · v{{ source.version }}
                <span v-if="source.page"> · 第{{ source.page }}页</span>
                <span v-else-if="source.section"> · {{ source.section }}</span>
              </button>
            </div>
            <div v-if="message.failed" class="retrieval-status">发送失败 · 未纳入后续上下文</div>
            <small
              >{{ message.role === 'assistant' ? '阅见 AI' : '你' }} · {{ message.time }}</small
            >
          </div>
        </div>
        <div v-if="thinking" class="message assistant">
          <span class="message-avatar"
            ><el-icon><MagicStick /></el-icon
          ></span>
          <div class="thinking-bubble"><i></i><i></i><i></i><span>DeepSeek 正在生成回答</span></div>
        </div>
        <div v-if="errorMessage" class="chat-error" role="alert">
          <el-icon><InfoFilled /></el-icon>{{ errorMessage }}
          <el-button v-if="pendingRequest" size="small" :disabled="thinking" @click="submitPending"
            >重试本次</el-button
          >
        </div>
      </div>

      <div class="suggestions">
        <button v-for="item in suggestions" :key="item" :disabled="thinking" @click="send(item)">
          {{ item }}
        </button>
      </div>
      <footer class="chat-input">
        <el-input
          v-model="input"
          type="textarea"
          :disabled="thinking"
          :autosize="{ minRows: 1, maxRows: 4 }"
          maxlength="4000"
          resize="none"
          :placeholder="
            mode === 'knowledge' ? '询问已发布的馆规或预约说明…' : '询问系统流程或描述你的空间需求…'
          "
          @keydown.enter.exact.prevent="send()"
        />
        <button :disabled="!input.trim() || thinking" @click="send()">
          <el-icon><Promotion /></el-icon>
        </button>
        <p>
          <el-icon><InfoFilled /></el-icon> AI 建议仅供参考，最终预约结果以管理员审核为准
          <span>Enter 发送</span>
        </p>
      </footer>
    </section>

    <aside class="agent-sidebar">
      <section class="agent-trace surface">
        <div class="side-title">
          <div>
            <span
              ><el-icon><Connection /></el-icon
            ></span>
            <div>
              <h3>当前请求状态</h3>
              <p>以接口实际返回为准</p>
            </div>
          </div>
        </div>
        <div class="request-status" role="status">
          <strong>{{ currentStatus }}</strong>
          <p>
            {{
              mode === 'knowledge'
                ? '检索已发布文档 → 校验有效版本 → DeepSeek 根据资料回答'
                : '普通聊天不检索知识库'
            }}
          </p>
          <p v-if="lastResult?.sources?.length">
            上一回答返回 {{ lastResult.sources.length }} 条来源，可点击查看。
          </p>
        </div>
      </section>

      <section class="knowledge-card surface">
        <div class="side-title">
          <div>
            <span class="book-icon"
              ><el-icon><Collection /></el-icon
            ></span>
            <div>
              <h3>当前能力</h3>
              <p>LangChain · DeepSeek · 百炼向量检索</p>
            </div>
          </div>
        </div>
        <ul class="capability-list">
          <li>
            <el-icon><Check /></el-icon><span>介绍空间预约与审核流程</span>
          </li>
          <li>
            <el-icon><Check /></el-icon><span>在本轮对话中保留上下文</span>
          </li>
          <li>
            <el-icon><Check /></el-icon><span>根据用户提供的信息给出建议</span>
          </li>
          <li>
            <el-icon><Collection /></el-icon><span>知识模式检索馆规并提供来源</span>
          </li>
          <li>
            <el-icon><InfoFilled /></el-icon><span>没有足够依据时明确拒答</span>
          </li>
        </ul>
      </section>

      <section class="capability-card">
        <span
          ><el-icon><InfoFilled /></el-icon
        ></span>
        <div>
          <strong>数据边界</strong>
          <p>知识库仅收录公开馆规和说明，不读取实时空闲或个人预约，也不会替你操作预约。</p>
        </div>
      </section>
    </aside>
    <el-dialog v-model="sourceDialog" title="知识库来源" width="min(680px, 94vw)">
      <div v-loading="sourceLoading" class="source-preview">
        <el-alert v-if="sourceError" type="warning" :closable="false" :title="sourceError" />
        <template v-if="sourceContent">
          <h3>{{ sourceContent.title }} · v{{ sourceContent.version }}</h3>
          <p v-if="sourceContent.page">第 {{ sourceContent.page }} 页</p>
          <p v-if="sourceContent.section">{{ sourceContent.section }}</p>
          <pre>{{ sourceContent.text }}</pre>
        </template>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.mode-select {
  width: 140px;
  margin-left: auto;
  flex: none;
}
.retrieval-status {
  margin-top: 7px;
  color: #64756f;
  font-size: 11px;
}
.answer-sources {
  display: grid;
  gap: 5px;
  margin-top: 8px;
}
.answer-sources button {
  padding: 7px 10px;
  text-align: left;
  color: #225c50;
  background: #f1f5ef;
  border: 1px solid #dbe5dc;
  border-radius: 6px;
  font-size: 11px;
  overflow-wrap: anywhere;
}
.request-status {
  margin-top: 18px;
  color: #455f6f;
  font-size: 12px;
  line-height: 1.8;
}
.request-status p {
  margin-top: 8px;
  color: #71847c;
}
.source-preview {
  min-height: 80px;
}
.source-preview pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.8;
  margin-top: 18px;
  font-family: inherit;
}
.assistant-page {
  height: calc(100vh - 158px);
  min-height: 610px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 310px;
  gap: 20px;
}
.chat-panel {
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.chat-header {
  height: 72px;
  display: flex;
  align-items: center;
  gap: 11px;
  flex: none;
  padding: 0 20px;
  border-bottom: 1px solid #e9eae5;
}
.ai-avatar {
  width: 39px;
  height: 39px;
  display: grid;
  place-items: center;
  position: relative;
  color: #fff;
  font-size: 19px;
  background: var(--navy-900);
  border-radius: 11px;
}
.ai-avatar i {
  position: absolute;
  right: -1px;
  bottom: -1px;
  width: 9px;
  height: 9px;
  background: var(--gold-500);
  border: 2px solid white;
  border-radius: 50%;
}
.chat-header h2 {
  color: var(--ink);
  font-family: Georgia, serif;
  font-size: 16px;
}
.chat-header p {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 2px;
  color: #8b9996;
  font-size: 8px;
}
.chat-header p span {
  width: 5px;
  height: 5px;
  background: var(--gold-500);
  border-radius: 50%;
}
.chat-header .el-tag {
  margin-left: auto;
}
.clear-chat {
  min-width: 44px;
  min-height: 44px;
  margin-left: 5px;
  padding: 6px;
  color: #78908c;
  background: transparent;
  border: 0;
}
.clear-chat:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.chat-body {
  flex: 1;
  overflow-y: auto;
  padding: 15px 25px 25px;
  scroll-behavior: smooth;
}
.day-divider {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 18px;
  color: #a1aaa7;
  font-size: 8px;
}
.day-divider::before,
.day-divider::after {
  content: '';
  height: 1px;
  flex: 1;
  background: #eeefeb;
}
.message {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  margin-bottom: 18px;
}
.message.user {
  justify-content: flex-end;
}
.message-avatar {
  width: 29px;
  height: 29px;
  display: grid;
  place-items: center;
  flex: none;
  color: #17413d;
  font-size: 13px;
  background: #a2e1cb;
  border-radius: 8px;
}
.message-wrap {
  max-width: min(650px, 82%);
}
.bubble {
  padding: 11px 14px;
  color: #445d59;
  font-size: 11px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
  background: #f1f5f2;
  border-radius: 3px 12px 12px 12px;
}
.message.user .bubble {
  color: white;
  background: #287b70;
  border-radius: 12px 3px 12px 12px;
}
.message-wrap > small {
  display: block;
  margin-top: 4px;
  color: #9ba6a3;
  font-size: 7px;
}
.message.user .message-wrap > small {
  text-align: right;
}
.thinking-bubble {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 12px 15px;
  color: #82918e;
  font-size: 9px;
  background: #f1f5f2;
  border-radius: 3px 12px 12px 12px;
}
.thinking-bubble i {
  width: 5px;
  height: 5px;
  background: #68af99;
  border-radius: 50%;
  animation: bounce 0.9s infinite alternate;
}
.thinking-bubble i:nth-child(2) {
  animation-delay: 0.2s;
}
.thinking-bubble i:nth-child(3) {
  animation-delay: 0.4s;
}
.thinking-bubble span {
  margin-left: 5px;
}
.chat-error {
  display: flex;
  align-items: center;
  gap: 5px;
  margin: -4px 0 12px 38px;
  color: #a15b4a;
  font-size: 8px;
}
@keyframes bounce {
  to {
    transform: translateY(-4px);
    opacity: 0.45;
  }
}
.suggestions {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  padding: 9px 18px;
  border-top: 1px solid #eceee9;
}
.suggestions button {
  min-height: 36px;
  flex: none;
  padding: 6px 9px;
  color: var(--navy-800);
  font-size: 9px;
  background: #f3f0e9;
  border: 1px solid #e3dccf;
  border-radius: 7px;
}
.suggestions button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.chat-input {
  position: relative;
  flex: none;
  padding: 10px 18px 12px;
}
.chat-input :deep(.el-textarea__inner) {
  min-height: 47px !important;
  padding: 13px 54px 13px 13px;
  border-radius: 11px;
}
.chat-input > button {
  width: 40px;
  height: 40px;
  display: grid;
  place-items: center;
  position: absolute;
  right: 23px;
  top: 13px;
  color: white;
  background: var(--navy-900);
  border: 0;
  border-radius: 9px;
}
.chat-input > button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.chat-input p {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 6px;
  color: #7f8d97;
  font-size: 8px;
}
.chat-input p span {
  margin-left: auto;
}
.agent-sidebar {
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 13px;
  overflow-y: auto;
}
.agent-trace,
.knowledge-card {
  padding: 16px;
}
.side-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.side-title > div {
  display: flex;
  align-items: center;
  gap: 9px;
}
.side-title > div > span {
  width: 31px;
  height: 31px;
  display: grid;
  place-items: center;
  color: var(--navy-800);
  background: #e8edf1;
  border-radius: 8px;
}
.side-title h3 {
  color: var(--ink);
  font-size: 11px;
}
.side-title p {
  margin-top: 2px;
  color: #7f8e99;
  font-size: 8px;
}
.trace-list {
  margin-top: 17px;
  padding-left: 3px;
}
.trace-step {
  min-height: 53px;
  display: flex;
  gap: 9px;
  position: relative;
}
.trace-step:not(:last-child)::after {
  content: '';
  position: absolute;
  left: 11px;
  top: 24px;
  bottom: 3px;
  width: 1px;
  background: #dfe6e1;
}
.trace-step > span {
  width: 23px;
  height: 23px;
  display: grid;
  place-items: center;
  z-index: 1;
  flex: none;
  color: #8c9b97;
  font-size: 10px;
  background: #f0f2ef;
  border-radius: 50%;
}
.trace-step.done > span {
  color: white;
  background: var(--navy-800);
}
.trace-step.active > span {
  color: var(--gold-700);
  background: var(--gold-100);
  box-shadow: 0 0 0 4px #faf6ee;
}
.trace-step div {
  flex: 1;
}
.trace-step strong {
  color: #455f6f;
  font-size: 9px;
}
.trace-step p {
  margin-top: 2px;
  color: #87959f;
  font-size: 8px;
}
.knowledge-card .book-icon {
  color: var(--gold-700);
  background: var(--gold-100);
}
.online-dot {
  width: 7px;
  height: 7px;
  background: var(--gold-500);
  border-radius: 50%;
  box-shadow: 0 0 0 3px #f8ecd8;
}
.capability-list {
  display: grid;
  gap: 10px;
  margin-top: 16px;
  padding: 0;
  list-style: none;
}
.capability-list li {
  display: flex;
  align-items: center;
  gap: 7px;
  color: #5c7182;
  font-size: 9px;
}
.capability-list .el-icon {
  flex: none;
  color: #4f7c66;
}
.capability-list .pending .el-icon {
  color: var(--gold-600);
}
.capability-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  color: white;
  background: var(--navy-900);
  border-radius: 13px;
}
.capability-card > span {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  flex: none;
  color: var(--navy-950);
  background: var(--gold-500);
  border-radius: 8px;
}
.capability-card strong {
  font-size: 9px;
}
.capability-card p {
  margin-top: 3px;
  color: #bdc9d1;
  font-size: 8px;
  line-height: 1.5;
}
@media (max-width: 1000px) {
  .assistant-page {
    height: auto;
    grid-template-columns: 1fr;
  }
  .chat-panel {
    height: 650px;
  }
  .agent-sidebar {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }
  .capability-card {
    grid-column: 1 / -1;
  }
}
@media (max-width: 600px) {
  .assistant-page {
    min-height: 0;
  }
  .chat-panel {
    height: calc(100vh - 120px);
    min-height: 590px;
  }
  .chat-body {
    padding: 14px;
  }
  .message-wrap {
    max-width: 88%;
  }
  .agent-sidebar {
    grid-template-columns: 1fr;
  }
  .capability-card {
    grid-column: auto;
  }
  .suggestions button {
    max-width: 220px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .chat-header .el-tag {
    display: none;
  }
}
</style>
