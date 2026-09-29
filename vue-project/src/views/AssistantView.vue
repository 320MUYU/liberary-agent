<script setup>
import { nextTick, onMounted, ref } from 'vue'
import BookingDialog from '@/components/BookingDialog.vue'
import { labs, loadLabs } from '@/store/labStore'

const input = ref('')
const thinking = ref(false)
const chatBody = ref()
const bookingOpen = ref(false)
// 实验室是异步取的，首屏时 labs 还是空的，所以先给 null
const selectedLab = ref(null)
const showAgentTrace = ref(true)
const suggestions = ['明天下午做机器视觉实验，4个人', '哪些实验室配有 GPU 工作站？', '嵌入式实验室的预约规则是什么？']
const messages = ref([
  { role: 'assistant', text: '你好，我是 LabMind AI 助理。你可以直接告诉我实验内容、人数和时间，我会结合实验室设备、预约规则与实时空闲情况，为你推荐合适的实验室。', time: '10:24' },
])

function scrollBottom() { nextTick(() => { if (chatBody.value) chatBody.value.scrollTop = chatBody.value.scrollHeight }) }
function replyFor(text) {
  if (/嵌入式|STM32|示波器/i.test(text)) return '根据知识库中的《实验室使用规范》，嵌入式系统实验室支持 STM32、示波器和逻辑分析仪。建议至少提前 1 天预约；如需携带自有硬件，请在补充说明中填写设备型号。当前最近空闲时段是今天 16:00。'
  if (/GPU|视觉|深度学习|人工智能/i.test(text)) return '我已检索设备清单并查询空闲时段。智能感知实验室 A-301 最匹配：配有 GPU 工作站和机器视觉平台，可容纳 24 人。明天下午 14:00—16:00 有空闲时段，推荐度 96%。'
  if (/规则|取消|审核/i.test(text)) return '预约需至少提前 2 小时提交，单次最长 4 小时。申请由实验室管理员审核；开始前 2 小时可自行取消，逾期未签到将记录一次违约。以上内容来自《学生实验室预约管理办法》。'
  return '我已经理解你的需求。综合设备匹配度、容纳人数和近期空闲时段，优先推荐智能感知实验室 A-301。你可以继续补充日期、人数和实验设备，我会把条件整理成预约申请。'
}

function send(text = input.value) {
  const value = text.trim()
  if (!value || thinking.value) return
  messages.value.push({ role: 'user', text: value, time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) })
  input.value = ''
  thinking.value = true
  showAgentTrace.value = true
  scrollBottom()
  window.setTimeout(() => {
    messages.value.push({ role: 'assistant', text: replyFor(value), time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }), recommendation: /GPU|视觉|实验|预约|明天/i.test(value) })
    thinking.value = false
    scrollBottom()
  }, 900)
}

function openBooking() { selectedLab.value = labs[0] || null; bookingOpen.value = true }

onMounted(() => {
  // 预约弹窗里要选实验室，先把列表拉回来
  loadLabs().catch(() => {})
})
</script>

<template>
  <div class="assistant-page">
    <section class="chat-panel surface">
      <header class="chat-header">
        <div class="ai-avatar"><el-icon><MagicStick /></el-icon><i></i></div>
        <div><h2>LabMind AI</h2><p><span></span> Agent 服务在线 · 已连接实验室数据</p></div>
        <el-tag type="success" effect="light" size="small">演示环境</el-tag>
        <button class="clear-chat" title="新建对话" @click="messages = messages.slice(0, 1)"><el-icon><EditPen /></el-icon></button>
      </header>

      <div ref="chatBody" class="chat-body">
        <div class="day-divider"><span>今天</span></div>
        <div v-for="(message, index) in messages" :key="index" :class="['message', message.role]">
          <span v-if="message.role === 'assistant'" class="message-avatar"><el-icon><MagicStick /></el-icon></span>
          <div class="message-wrap">
            <div class="bubble">{{ message.text }}</div>
            <small>{{ message.role === 'assistant' ? 'LabMind AI' : '你' }} · {{ message.time }}</small>
            <div v-if="message.recommendation" class="recommendation-card">
              <div class="recommend-head"><span><el-icon><DataAnalysis /></el-icon></span><div><small>最优匹配 · 96%</small><strong>智能感知实验室</strong></div><el-tag type="success" effect="light" size="small">可预约</el-tag></div>
              <div class="recommend-meta"><span><el-icon><Location /></el-icon>A-301</span><span><el-icon><Clock /></el-icon>明日 14:00—16:00</span><span><el-icon><User /></el-icon>可容纳 24 人</span></div>
              <div class="recommend-tags"><span>GPU 工作站</span><span>机器视觉平台</span><span>边缘计算盒</span></div>
              <div class="recommend-actions"><button @click="openBooking">带入信息并预约 <el-icon><Right /></el-icon></button><button @click="send('还有其他合适的实验室吗？')">换一个推荐</button></div>
            </div>
          </div>
        </div>
        <div v-if="thinking" class="message assistant">
          <span class="message-avatar"><el-icon><MagicStick /></el-icon></span>
          <div class="thinking-bubble"><i></i><i></i><i></i><span>Agent 正在分析需求</span></div>
        </div>
      </div>

      <div class="suggestions"><button v-for="item in suggestions" :key="item" @click="send(item)">{{ item }}</button></div>
      <footer class="chat-input">
        <el-input v-model="input" type="textarea" :autosize="{ minRows: 1, maxRows: 4 }" resize="none" placeholder="描述你的实验需求，例如：周三下午需要 4 台 GPU…" @keydown.enter.exact.prevent="send()" />
        <button :disabled="!input.trim() || thinking" @click="send()"><el-icon><Promotion /></el-icon></button>
        <p><el-icon><InfoFilled /></el-icon> AI 建议仅供参考，最终预约结果以管理员审核为准 <span>Enter 发送</span></p>
      </footer>
    </section>

    <aside class="agent-sidebar">
      <section class="agent-trace surface">
        <div class="side-title"><div><span><el-icon><Connection /></el-icon></span><div><h3>Agent 执行轨迹</h3><p>LangGraph 工作流</p></div></div><button @click="showAgentTrace = !showAgentTrace"><el-icon><ArrowUp v-if="showAgentTrace"/><ArrowDown v-else/></el-icon></button></div>
        <div v-if="showAgentTrace" class="trace-list">
          <div class="trace-step done"><span><el-icon><Check /></el-icon></span><div><strong>理解用户需求</strong><p>提取时间、人数与设备条件</p></div><small>0.2s</small></div>
          <div class="trace-step done"><span><el-icon><Check /></el-icon></span><div><strong>检索知识库</strong><p>ChromaDB 命中 3 个相关片段</p></div><small>0.4s</small></div>
          <div class="trace-step active"><span><el-icon><Search /></el-icon></span><div><strong>查询可用时段</strong><p>调用实验室业务数据工具</p></div><small>实时</small></div>
          <div class="trace-step"><span><el-icon><MagicStick /></el-icon></span><div><strong>生成预约建议</strong><p>综合排序并等待用户确认</p></div></div>
        </div>
      </section>

      <section class="knowledge-card surface">
        <div class="side-title"><div><span class="book-icon"><el-icon><Collection /></el-icon></span><div><h3>知识库</h3><p>RAG 检索已启用</p></div></div><i class="online-dot"></i></div>
        <div class="knowledge-stats"><div><strong>12</strong><span>知识文档</span></div><div><strong>186</strong><span>文本片段</span></div><div><strong>98%</strong><span>索引完成</span></div></div>
        <div class="source-list"><p>本轮引用来源</p><div><span>PDF</span><div><strong>实验室预约管理办法</strong><small>匹配度 94%</small></div></div><div><span>DOC</span><div><strong>设备与软件环境清单</strong><small>匹配度 88%</small></div></div></div>
      </section>

      <section class="capability-card"><span><el-icon><Cpu /></el-icon></span><div><strong>我能帮你</strong><p>问答知识 · 查询数据 · 匹配实验室 · 辅助预约</p></div></section>
    </aside>
    <BookingDialog v-model="bookingOpen" :selected-lab="selectedLab" />
  </div>
</template>

<style scoped>
.assistant-page { height: calc(100vh - 158px); min-height: 610px; display: grid; grid-template-columns: minmax(0, 1fr) 310px; gap: 20px; }.chat-panel { min-height: 0; display: flex; flex-direction: column; overflow: hidden; }.chat-header { height: 72px; display: flex; align-items: center; gap: 11px; flex: none; padding: 0 20px; border-bottom: 1px solid #e9eae5; }.ai-avatar { width: 39px; height: 39px; display: grid; place-items: center; position: relative; color: #173b39; font-size: 19px; background: var(--mint); border-radius: 11px; }.ai-avatar i { position: absolute; right: -1px; bottom: -1px; width: 9px; height: 9px; background: #50b98f; border: 2px solid white; border-radius: 50%; }.chat-header h2 { color: var(--ink); font-family: Georgia, serif; font-size: 16px; }.chat-header p { display: flex; align-items: center; gap: 5px; margin-top: 2px; color: #8b9996; font-size: 8px; }.chat-header p span { width: 5px; height: 5px; background: #5fbe9b; border-radius: 50%; }.chat-header .el-tag { margin-left: auto; }.clear-chat { margin-left: 5px; padding: 6px; color: #78908c; background: transparent; border: 0; }
.chat-body { flex: 1; overflow-y: auto; padding: 15px 25px 25px; scroll-behavior: smooth; }.day-divider { display: flex; align-items: center; gap: 10px; margin-bottom: 18px; color: #a1aaa7; font-size: 8px; }.day-divider::before,.day-divider::after { content: ''; height: 1px; flex: 1; background: #eeefeb; }.message { display: flex; align-items: flex-start; gap: 9px; margin-bottom: 18px; }.message.user { justify-content: flex-end; }.message-avatar { width: 29px; height: 29px; display: grid; place-items: center; flex: none; color: #17413d; font-size: 13px; background: #a2e1cb; border-radius: 8px; }.message-wrap { max-width: min(650px, 82%); }.bubble { padding: 11px 14px; color: #445d59; font-size: 11px; line-height: 1.75; background: #f1f5f2; border-radius: 3px 12px 12px 12px; }.message.user .bubble { color: white; background: #287b70; border-radius: 12px 3px 12px 12px; }.message-wrap > small { display: block; margin-top: 4px; color: #9ba6a3; font-size: 7px; }.message.user .message-wrap > small { text-align: right; }.thinking-bubble { display: flex; align-items: center; gap: 4px; padding: 12px 15px; color: #82918e; font-size: 9px; background: #f1f5f2; border-radius: 3px 12px 12px 12px; }.thinking-bubble i { width: 5px; height: 5px; background: #68af99; border-radius: 50%; animation: bounce .9s infinite alternate; }.thinking-bubble i:nth-child(2) { animation-delay: .2s; }.thinking-bubble i:nth-child(3) { animation-delay: .4s; }.thinking-bubble span { margin-left: 5px; }@keyframes bounce { to { transform: translateY(-4px); opacity: .45; } }
.recommendation-card { margin-top: 9px; overflow: hidden; background: white; border: 1px solid #dfe8e2; border-radius: 11px; box-shadow: 0 8px 20px rgba(42,79,76,.05); }.recommend-head { display: flex; align-items: center; gap: 10px; padding: 12px; background: #f3f8f5; }.recommend-head > span { width: 31px; height: 31px; display: grid; place-items: center; color: #236f64; background: #dcefe8; border-radius: 8px; }.recommend-head div { flex: 1; }.recommend-head small,.recommend-head strong { display: block; }.recommend-head small { color: #5a9d8a; font-size: 7px; font-weight: 700; }.recommend-head strong { margin-top: 2px; color: #274945; font-size: 11px; }.recommend-meta { display: flex; flex-wrap: wrap; gap: 13px; padding: 11px 12px 5px; }.recommend-meta span { display: flex; align-items: center; gap: 4px; color: #778a86; font-size: 8px; }.recommend-tags { display: flex; gap: 5px; padding: 5px 12px 11px; }.recommend-tags span { padding: 3px 6px; color: #5f7773; font-size: 7px; background: #f0f4f1; border-radius: 4px; }.recommend-actions { display: flex; border-top: 1px solid #eceee9; }.recommend-actions button { flex: 1; display: flex; align-items: center; justify-content: center; gap: 4px; padding: 9px; color: #247267; font-size: 8px; font-weight: 700; background: white; border: 0; }.recommend-actions button + button { color: #7b8986; border-left: 1px solid #eceee9; }
.suggestions { display: flex; gap: 6px; overflow-x: auto; padding: 9px 18px; border-top: 1px solid #eceee9; }.suggestions button { flex: none; padding: 6px 9px; color: #627b77; font-size: 8px; background: #f2f6f3; border: 1px solid #e1e8e3; border-radius: 7px; }.chat-input { position: relative; flex: none; padding: 10px 18px 12px; }.chat-input :deep(.el-textarea__inner) { min-height: 47px !important; padding: 13px 46px 13px 13px; border-radius: 11px; }.chat-input > button { width: 32px; height: 32px; display: grid; place-items: center; position: absolute; right: 26px; top: 17px; color: white; background: var(--mint-dark); border: 0; border-radius: 8px; }.chat-input > button:disabled { opacity: .4; cursor: not-allowed; }.chat-input p { display: flex; align-items: center; gap: 4px; margin-top: 6px; color: #9aa5a2; font-size: 7px; }.chat-input p span { margin-left: auto; }
.agent-sidebar { min-height: 0; display: flex; flex-direction: column; gap: 13px; overflow-y: auto; }.agent-trace,.knowledge-card { padding: 16px; }.side-title { display: flex; align-items: center; justify-content: space-between; }.side-title > div { display: flex; align-items: center; gap: 9px; }.side-title > div > span { width: 31px; height: 31px; display: grid; place-items: center; color: #206a61; background: #e2f1ec; border-radius: 8px; }.side-title h3 { color: var(--ink); font-size: 11px; }.side-title p { margin-top: 2px; color: #94a09d; font-size: 7px; }.side-title button { padding: 5px; color: #82918e; background: none; border: 0; }.trace-list { margin-top: 17px; padding-left: 3px; }.trace-step { min-height: 53px; display: flex; gap: 9px; position: relative; }.trace-step:not(:last-child)::after { content: ''; position: absolute; left: 11px; top: 24px; bottom: 3px; width: 1px; background: #dfe6e1; }.trace-step > span { width: 23px; height: 23px; display: grid; place-items: center; z-index: 1; flex: none; color: #8c9b97; font-size: 10px; background: #f0f2ef; border-radius: 50%; }.trace-step.done > span { color: white; background: #65b99e; }.trace-step.active > span { color: #276f66; background: #dff0ea; box-shadow: 0 0 0 4px #f1f8f5; }.trace-step div { flex: 1; }.trace-step strong { color: #455f5b; font-size: 9px; }.trace-step p { margin-top: 2px; color: #99a4a1; font-size: 7px; }.trace-step small { color: #91a09d; font-size: 7px; }.knowledge-card .book-icon { color: #7a648f; background: #eee9f1; }.online-dot { width: 7px; height: 7px; background: #5eb996; border-radius: 50%; box-shadow: 0 0 0 3px #e6f4ee; }.knowledge-stats { display: grid; grid-template-columns: repeat(3, 1fr); margin-top: 15px; padding: 12px 0; background: #f8f9f6; border-radius: 8px; }.knowledge-stats div { text-align: center; border-right: 1px solid #e8eae5; }.knowledge-stats div:last-child { border: 0; }.knowledge-stats strong,.knowledge-stats span { display: block; }.knowledge-stats strong { color: #345953; font-family: Georgia,serif; font-size: 14px; }.knowledge-stats span { color: #9aa4a1; font-size: 7px; }.source-list > p { margin: 13px 0 7px; color: #8e9b98; font-size: 7px; font-weight: 700; }.source-list > div { display: flex; align-items: center; gap: 8px; padding: 7px 0; border-top: 1px solid #edefea; }.source-list > div > span { padding: 3px 5px; color: #55736e; font-size: 6px; background: #eaf2ef; border-radius: 3px; }.source-list div div { flex: 1; }.source-list strong,.source-list small { display: block; }.source-list strong { color: #4c6561; font-size: 8px; }.source-list small { margin-top: 2px; color: #9ca5a3; font-size: 6px; }.capability-card { display: flex; align-items: center; gap: 10px; padding: 14px 16px; color: white; background: #1d5552; border-radius: 13px; }.capability-card > span { width: 32px; height: 32px; display: grid; place-items: center; color: #173c3a; background: var(--mint); border-radius: 8px; }.capability-card strong { font-size: 9px; }.capability-card p { margin-top: 3px; color: #9dbdb9; font-size: 7px; }
@media (max-width: 1000px) { .assistant-page { height: auto; grid-template-columns: 1fr; }.chat-panel { height: 650px; }.agent-sidebar { display: grid; grid-template-columns: 1fr 1fr; }.capability-card { grid-column: 1 / -1; } }
@media (max-width: 600px) { .assistant-page { min-height: 0; }.chat-panel { height: calc(100vh - 120px); min-height: 590px; }.chat-body { padding: 14px; }.message-wrap { max-width: 88%; }.agent-sidebar { grid-template-columns: 1fr; }.capability-card { grid-column: auto; }.suggestions button { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.chat-header .el-tag { display: none; } }
</style>
