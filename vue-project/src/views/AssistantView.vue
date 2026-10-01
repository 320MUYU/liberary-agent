<script setup>
import { nextTick, ref } from 'vue'
import { chatApi } from '@/aiApi'

const input = ref('')
const thinking = ref(false)
const chatBody = ref()
const errorMessage = ref('')
const suggestions = ['明天下午有哪些适合 4 人讨论的空间？', '哪些空间配有显示屏？', '学习空间的预约规则是什么？']

function currentTime() {
  return new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function welcomeMessage() {
  return {
    role: 'assistant',
    text: '你好，我是阅见 AI 空间助手。我可以介绍学习空间预约流程，也可以根据你提供的信息给出建议。当前尚未接入 RAG 与实时业务数据，空间、设施和预约状态请以系统页面为准。',
    time: currentTime(),
  }
}

const messages = ref([welcomeMessage()])

function scrollBottom() { nextTick(() => { if (chatBody.value) chatBody.value.scrollTop = chatBody.value.scrollHeight }) }

async function send(text = input.value) {
  const value = text.trim()
  if (!value || thinking.value) return

  messages.value.push({ role: 'user', text: value, time: currentTime() })
  input.value = ''
  thinking.value = true
  errorMessage.value = ''
  scrollBottom()

  try {
    const history = messages.value.slice(-30).map((message) => ({
      role: message.role,
      content: message.text,
    }))
    const reply = await chatApi(history)
    messages.value.push({ role: 'assistant', text: reply.content, time: currentTime() })
  } catch {
    errorMessage.value = '本次回答生成失败，你可以稍后重新发送。'
  } finally {
    thinking.value = false
    scrollBottom()
  }
}

function resetConversation() {
  messages.value = [welcomeMessage()]
  input.value = ''
  errorMessage.value = ''
}
</script>

<template>
  <div class="assistant-page">
    <section class="chat-panel surface">
      <header class="chat-header">
        <div class="ai-avatar"><el-icon><MagicStick /></el-icon><i></i></div>
        <div><h2>阅见 AI</h2><p><span></span> LangChain · DeepSeek</p></div>
        <el-tag type="success" effect="light" size="small">AI 对话</el-tag>
        <button class="clear-chat" title="新建对话" :disabled="thinking" @click="resetConversation"><el-icon><EditPen /></el-icon></button>
      </header>

      <div ref="chatBody" class="chat-body">
        <div class="day-divider"><span>今天</span></div>
        <div v-for="(message, index) in messages" :key="index" :class="['message', message.role]">
          <span v-if="message.role === 'assistant'" class="message-avatar"><el-icon><MagicStick /></el-icon></span>
          <div class="message-wrap">
            <div class="bubble">{{ message.text }}</div>
            <small>{{ message.role === 'assistant' ? '阅见 AI' : '你' }} · {{ message.time }}</small>
          </div>
        </div>
        <div v-if="thinking" class="message assistant">
          <span class="message-avatar"><el-icon><MagicStick /></el-icon></span>
          <div class="thinking-bubble"><i></i><i></i><i></i><span>DeepSeek 正在生成回答</span></div>
        </div>
        <div v-if="errorMessage" class="chat-error"><el-icon><InfoFilled /></el-icon>{{ errorMessage }}</div>
      </div>

      <div class="suggestions"><button v-for="item in suggestions" :key="item" :disabled="thinking" @click="send(item)">{{ item }}</button></div>
      <footer class="chat-input">
        <el-input v-model="input" type="textarea" :autosize="{ minRows: 1, maxRows: 4 }" maxlength="4000" resize="none" placeholder="描述你的空间需求，例如：周三下午需要 4 人讨论…" @keydown.enter.exact.prevent="send()" />
        <button :disabled="!input.trim() || thinking" @click="send()"><el-icon><Promotion /></el-icon></button>
        <p><el-icon><InfoFilled /></el-icon> AI 建议仅供参考，最终预约结果以管理员审核为准 <span>Enter 发送</span></p>
      </footer>
    </section>

    <aside class="agent-sidebar">
      <section class="agent-trace surface">
        <div class="side-title"><div><span><el-icon><Connection /></el-icon></span><div><h3>对话处理流程</h3><p>LangChain 消息链</p></div></div></div>
        <div class="trace-list">
          <div class="trace-step done"><span><el-icon><Check /></el-icon></span><div><strong>校验消息</strong><p>限制角色、条数与内容长度</p></div></div>
          <div class="trace-step done"><span><el-icon><Check /></el-icon></span><div><strong>整理上下文</strong><p>注入预约规则和历史消息</p></div></div>
          <div :class="['trace-step', { active: thinking }]"><span><el-icon><MagicStick /></el-icon></span><div><strong>生成回答</strong><p>调用 DeepSeek 对话模型</p></div></div>
        </div>
      </section>

      <section class="knowledge-card surface">
        <div class="side-title"><div><span class="book-icon"><el-icon><Collection /></el-icon></span><div><h3>当前能力</h3><p>纯大模型对话</p></div></div><i class="online-dot"></i></div>
        <ul class="capability-list">
          <li><el-icon><Check /></el-icon><span>介绍空间预约与审核流程</span></li>
          <li><el-icon><Check /></el-icon><span>在本轮对话中保留上下文</span></li>
          <li><el-icon><Check /></el-icon><span>根据用户提供的信息给出建议</span></li>
          <li class="pending"><el-icon><Clock /></el-icon><span>RAG 知识库将在后续接入</span></li>
        </ul>
      </section>

      <section class="capability-card"><span><el-icon><InfoFilled /></el-icon></span><div><strong>数据边界</strong><p>当前未接入 RAG 与实时数据，空间、设施和预约状态请前往对应页面查看</p></div></section>
    </aside>
  </div>
</template>

<style scoped>
.assistant-page { height: calc(100vh - 158px); min-height: 610px; display: grid; grid-template-columns: minmax(0, 1fr) 310px; gap: 20px; }.chat-panel { min-height: 0; display: flex; flex-direction: column; overflow: hidden; }.chat-header { height: 72px; display: flex; align-items: center; gap: 11px; flex: none; padding: 0 20px; border-bottom: 1px solid #e9eae5; }.ai-avatar { width: 39px; height: 39px; display: grid; place-items: center; position: relative; color: #fff; font-size: 19px; background: var(--navy-900); border-radius: 11px; }.ai-avatar i { position: absolute; right: -1px; bottom: -1px; width: 9px; height: 9px; background: var(--gold-500); border: 2px solid white; border-radius: 50%; }.chat-header h2 { color: var(--ink); font-family: Georgia, serif; font-size: 16px; }.chat-header p { display: flex; align-items: center; gap: 5px; margin-top: 2px; color: #8b9996; font-size: 8px; }.chat-header p span { width: 5px; height: 5px; background: var(--gold-500); border-radius: 50%; }.chat-header .el-tag { margin-left: auto; }.clear-chat { min-width: 44px; min-height: 44px; margin-left: 5px; padding: 6px; color: #78908c; background: transparent; border: 0; }.clear-chat:disabled { opacity: .4; cursor: not-allowed; }
.chat-body { flex: 1; overflow-y: auto; padding: 15px 25px 25px; scroll-behavior: smooth; }.day-divider { display: flex; align-items: center; gap: 10px; margin-bottom: 18px; color: #a1aaa7; font-size: 8px; }.day-divider::before,.day-divider::after { content: ''; height: 1px; flex: 1; background: #eeefeb; }.message { display: flex; align-items: flex-start; gap: 9px; margin-bottom: 18px; }.message.user { justify-content: flex-end; }.message-avatar { width: 29px; height: 29px; display: grid; place-items: center; flex: none; color: #17413d; font-size: 13px; background: #a2e1cb; border-radius: 8px; }.message-wrap { max-width: min(650px, 82%); }.bubble { padding: 11px 14px; color: #445d59; font-size: 11px; line-height: 1.75; white-space: pre-wrap; word-break: break-word; background: #f1f5f2; border-radius: 3px 12px 12px 12px; }.message.user .bubble { color: white; background: #287b70; border-radius: 12px 3px 12px 12px; }.message-wrap > small { display: block; margin-top: 4px; color: #9ba6a3; font-size: 7px; }.message.user .message-wrap > small { text-align: right; }.thinking-bubble { display: flex; align-items: center; gap: 4px; padding: 12px 15px; color: #82918e; font-size: 9px; background: #f1f5f2; border-radius: 3px 12px 12px 12px; }.thinking-bubble i { width: 5px; height: 5px; background: #68af99; border-radius: 50%; animation: bounce .9s infinite alternate; }.thinking-bubble i:nth-child(2) { animation-delay: .2s; }.thinking-bubble i:nth-child(3) { animation-delay: .4s; }.thinking-bubble span { margin-left: 5px; }.chat-error { display: flex; align-items: center; gap: 5px; margin: -4px 0 12px 38px; color: #a15b4a; font-size: 8px; }@keyframes bounce { to { transform: translateY(-4px); opacity: .45; } }
.suggestions { display: flex; gap: 6px; overflow-x: auto; padding: 9px 18px; border-top: 1px solid #eceee9; }.suggestions button { min-height: 36px; flex: none; padding: 6px 9px; color: var(--navy-800); font-size: 9px; background: #f3f0e9; border: 1px solid #e3dccf; border-radius: 7px; }.suggestions button:disabled { opacity: .45; cursor: not-allowed; }.chat-input { position: relative; flex: none; padding: 10px 18px 12px; }.chat-input :deep(.el-textarea__inner) { min-height: 47px !important; padding: 13px 54px 13px 13px; border-radius: 11px; }.chat-input > button { width: 40px; height: 40px; display: grid; place-items: center; position: absolute; right: 23px; top: 13px; color: white; background: var(--navy-900); border: 0; border-radius: 9px; }.chat-input > button:disabled { opacity: .4; cursor: not-allowed; }.chat-input p { display: flex; align-items: center; gap: 4px; margin-top: 6px; color: #7f8d97; font-size: 8px; }.chat-input p span { margin-left: auto; }
.agent-sidebar { min-height: 0; display: flex; flex-direction: column; gap: 13px; overflow-y: auto; }.agent-trace,.knowledge-card { padding: 16px; }.side-title { display: flex; align-items: center; justify-content: space-between; }.side-title > div { display: flex; align-items: center; gap: 9px; }.side-title > div > span { width: 31px; height: 31px; display: grid; place-items: center; color: var(--navy-800); background: #e8edf1; border-radius: 8px; }.side-title h3 { color: var(--ink); font-size: 11px; }.side-title p { margin-top: 2px; color: #7f8e99; font-size: 8px; }.trace-list { margin-top: 17px; padding-left: 3px; }.trace-step { min-height: 53px; display: flex; gap: 9px; position: relative; }.trace-step:not(:last-child)::after { content: ''; position: absolute; left: 11px; top: 24px; bottom: 3px; width: 1px; background: #dfe6e1; }.trace-step > span { width: 23px; height: 23px; display: grid; place-items: center; z-index: 1; flex: none; color: #8c9b97; font-size: 10px; background: #f0f2ef; border-radius: 50%; }.trace-step.done > span { color: white; background: var(--navy-800); }.trace-step.active > span { color: var(--gold-700); background: var(--gold-100); box-shadow: 0 0 0 4px #faf6ee; }.trace-step div { flex: 1; }.trace-step strong { color: #455f6f; font-size: 9px; }.trace-step p { margin-top: 2px; color: #87959f; font-size: 8px; }.knowledge-card .book-icon { color: var(--gold-700); background: var(--gold-100); }.online-dot { width: 7px; height: 7px; background: var(--gold-500); border-radius: 50%; box-shadow: 0 0 0 3px #f8ecd8; }.capability-list { display: grid; gap: 10px; margin-top: 16px; padding: 0; list-style: none; }.capability-list li { display: flex; align-items: center; gap: 7px; color: #5c7182; font-size: 9px; }.capability-list .el-icon { flex: none; color: #4f7c66; }.capability-list .pending .el-icon { color: var(--gold-600); }.capability-card { display: flex; align-items: center; gap: 10px; padding: 14px 16px; color: white; background: var(--navy-900); border-radius: 13px; }.capability-card > span { width: 32px; height: 32px; display: grid; place-items: center; flex: none; color: var(--navy-950); background: var(--gold-500); border-radius: 8px; }.capability-card strong { font-size: 9px; }.capability-card p { margin-top: 3px; color: #bdc9d1; font-size: 8px; line-height: 1.5; }
@media (max-width: 1000px) { .assistant-page { height: auto; grid-template-columns: 1fr; }.chat-panel { height: 650px; }.agent-sidebar { display: grid; grid-template-columns: 1fr 1fr; }.capability-card { grid-column: 1 / -1; } }
@media (max-width: 600px) { .assistant-page { min-height: 0; }.chat-panel { height: calc(100vh - 120px); min-height: 590px; }.chat-body { padding: 14px; }.message-wrap { max-width: 88%; }.agent-sidebar { grid-template-columns: 1fr; }.capability-card { grid-column: auto; }.suggestions button { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.chat-header .el-tag { display: none; } }
</style>
