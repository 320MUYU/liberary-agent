<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { getUserInfo } from '@/auth'
import { reservationError } from '@/utils/spaceReservation'
import BookBorrowAgent from '@/components/BookBorrowAgent.vue'
import SpaceReservationAgent from '@/components/SpaceReservationAgent.vue'
import {
  startWorkflow, getWorkflow, retryWorkflow, cancelWorkflow,
  setWorkflowConditions, clarifyWorkflow, operateWorkflowStep
} from '@/api/workflowApi'

const query = ref('')
const supplement = ref('')
const run = ref(null)
const busy = ref(false)
const error = ref('')
const form = ref({ date: '', start: '', end: '', people: '', purpose: '', note: '' })
const storageKey = `library-workflow-${getUserInfo()?.id}`
const workflowId = ref(sessionStorage.getItem(storageKey) || '')
const labels = {
  planning: '等待规划', ready: '等待开始下一步', waiting: '等待你的选择或确认',
  needs_conditions: '请补充预约条件', needs_clarification: '请补充需求',
  retryable: '本次未完成，可以重试', partial_failure: '部分完成，请查看未完成步骤',
  budget_exceeded: '已达到执行上限', completed: '步骤已全部结束', cancelled: '已停止后续步骤'
}
const stepLabels = { queued: '待执行', running: '处理中', waiting: '等待操作', completed: '已完成', failed: '未完成', skipped: '已跳过', cancelled: '已取消' }
let active = true
onUnmounted(() => { active = false })

async function perform(operation) {
  if (busy.value) return null
  busy.value = true
  error.value = ''
  try {
    const result = await operation()
    if (active) {
      run.value = result
      if (result.conditions) form.value = { ...result.conditions, note: result.conditions.note || '' }
      return result
    }
  } catch (failure) {
    if (active) error.value = failure.message || '请求未完成，请刷新任务状态。'
  } finally {
    if (active) busy.value = false
  }
  return null
}

async function start() {
  if (busy.value || run.value || !query.value.trim()) return
  if (query.value.trim().length > 1000) { error.value = '需求不能超过1000字。'; return }
  if (!workflowId.value) workflowId.value = crypto.randomUUID()
  sessionStorage.setItem(storageKey, workflowId.value)
  await perform(() => startWorkflow({ request_id: workflowId.value, query: query.value.trim() }))
}
async function refresh() {
  if (workflowId.value) await perform(() => getWorkflow(workflowId.value))
}
async function advance() {
  if (workflowId.value) await perform(() => retryWorkflow(workflowId.value))
}
async function submitConditions() {
  if (busy.value) return
  error.value = reservationError(form.value)
  if (error.value) return
  await perform(() => setWorkflowConditions(workflowId.value, {
    ...form.value, purpose: form.value.purpose.trim(), note: form.value.note.trim() || null
  }))
}
async function clarify() {
  if (!supplement.value.trim()) return
  await perform(() => clarifyWorkflow(workflowId.value, supplement.value.trim()))
}
async function stop() {
  if (workflowId.value) await perform(() => cancelWorkflow(workflowId.value))
}
async function restart() {
  if (busy.value) return
  if (run.value && !['completed', 'cancelled'].includes(run.value.status)) {
    await stop()
    if (run.value?.status !== 'cancelled') return
  }
  workflowId.value = ''; run.value = null; error.value = ''; query.value = ''; supplement.value = ''
  sessionStorage.removeItem(storageKey)
}
async function stepAction(stepId, operation, payload = {}) {
  const result = await perform(() => operation === 'view'
    ? getWorkflow(workflowId.value)
    : operation === 'retry'
      ? retryWorkflow(workflowId.value)
      : operateWorkflowStep(workflowId.value, { ...payload, operation, step_id: stepId }))
  if (!result) throw new Error(error.value || '请求尚未完成，请刷新任务状态。')
  return result.steps.find((step) => step.id === stepId)?.result
}
function managed(step) {
  return {
    run: step.result, busy: busy.value,
    readOnly: step.spec.read_only || run.value.status === 'cancelled' || ['skipped', 'cancelled'].includes(step.status),
    operate: (operation, payload) => stepAction(step.id, operation, payload)
  }
}
onMounted(refresh)
</script>

<template>
  <div class="workflow-assistant">
    <div class="workflow-intro">
      <span class="eyebrow">图书与空间 · 一次安排</span>
      <h3>把这次学习需要的事，一起告诉我</h3>
      <p>我会拆成可核对的步骤。借阅、归还和预约都需要你逐项选择并确认，最终由管理员办理。</p>
    </div>
    <form v-if="!run" class="workflow-query" @submit.prevent="start">
      <el-input v-model="query" type="textarea" :rows="3" maxlength="1000" aria-label="组合任务需求" placeholder="例如：找多智能体相关书籍，再帮我预约一个有投影的研讨室用于课程讨论。" :disabled="busy" />
      <el-button type="primary" native-type="submit" :disabled="busy || !query.trim()" :loading="busy">生成任务计划</el-button>
    </form>
    <el-alert v-if="error" :title="error" type="warning" :closable="false" show-icon />
    <p v-if="busy" role="status">正在处理，请稍候…</p>
    <div v-if="workflowId" class="workflow-controls">
      <el-button :disabled="busy" @click="refresh">刷新任务状态</el-button>
      <el-button v-if="run && !['completed', 'cancelled'].includes(run.status)" :disabled="busy" @click="stop">停止后续步骤</el-button>
      <el-button :disabled="busy" @click="restart">开始新任务</el-button>
    </div>
    <section v-if="run" class="workflow-progress" aria-label="组合任务进度">
      <h3>{{ labels[run.status] || '请刷新查看状态' }}</h3>
      <p class="original-query">{{ run.query }}</p>
      <p>{{ run.message }}</p>
      <p v-if="run.conditions" class="bound-conditions">已确认条件：{{ run.conditions.date }} {{ run.conditions.start }}—{{ run.conditions.end }}（北京时间）· {{ run.conditions.people }} 人 · {{ run.conditions.purpose }}</p>
      <form v-if="run.status === 'needs_clarification'" class="workflow-query" @submit.prevent="clarify">
        <el-input v-model="supplement" maxlength="1000" aria-label="补充任务需求" :disabled="busy" />
        <el-button native-type="submit" :disabled="busy || !supplement.trim()">补充需求</el-button>
      </form>
      <form v-if="run.status === 'needs_conditions'" class="workflow-conditions" @submit.prevent="submitConditions">
        <fieldset :disabled="busy">
          <label>预约日期<input v-model="form.date" type="date" required aria-label="组合预约日期" /></label>
          <label>人数<input v-model.number="form.people" type="number" min="1" max="1000" required aria-label="组合预约人数" /></label>
          <label>开始时间<input v-model="form.start" type="time" required aria-label="组合开始时间" /></label>
          <label>结束时间<input v-model="form.end" type="time" required aria-label="组合结束时间" /></label>
          <label>用途<input v-model="form.purpose" maxlength="255" required aria-label="组合预约用途" /></label>
          <label>备注<input v-model="form.note" maxlength="200" aria-label="组合预约备注" /></label>
        </fieldset>
        <p>北京时间，至少提前两小时。请核对条件；提交申请前还需要选择空间并再次确认。</p>
        <el-button type="primary" native-type="submit" :disabled="busy">确认这些查询条件</el-button>
      </form>
      <el-button v-if="['planning', 'ready', 'retryable', 'partial_failure', 'waiting'].includes(run.status)" type="primary" :disabled="busy" @click="advance">{{ run.status === 'ready' ? '开始下一步' : '继续未完成步骤' }}</el-button>
      <ol class="workflow-steps">
        <li v-for="step in run.steps" :key="step.id" class="workflow-step">
          <div class="step-heading">
            <h4>{{ step.position + 1 }}. {{ step.spec.title }}</h4>
            <el-tag :type="step.status === 'completed' ? 'success' : 'info'">{{ stepLabels[step.status] }}</el-tag>
            <span>{{ step.spec.read_only ? '只查询' : '需要逐项确认' }}</span>
            <el-button v-if="!['completed', 'skipped', 'cancelled'].includes(step.status) && !['completed', 'cancelled'].includes(run.status) && step.id === run.steps.find((item) => !['completed', 'skipped', 'cancelled'].includes(item.status))?.id" text :disabled="busy" @click="stepAction(step.id, 'skip').catch(() => {})">跳过此步骤</el-button>
          </div>
          <template v-if="step.result">
            <SpaceReservationAgent v-if="step.spec.task_type === 'reservation'" :managed="managed(step)" />
            <BookBorrowAgent v-else :managed="managed(step)" />
          </template>
        </li>
      </ol>
    </section>
  </div>
</template>

<style scoped>
.workflow-assistant { flex: 1; min-width: 0; overflow-y: auto; padding: 24px 30px; }
.workflow-intro { margin-bottom: 20px; }
.eyebrow { color: #258675; font-size: 12px; letter-spacing: 1px; }
.workflow-intro h3 { margin: 10px 0; font-size: 22px; }
.workflow-intro p, .workflow-progress p { line-height: 1.7; color: #667581; }
.workflow-query { display: grid; gap: 12px; margin: 18px 0; }
.workflow-query .el-button { justify-self: start; }
.workflow-controls, .step-heading { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin: 16px 0; }
.step-heading h4 { margin: 0; font-size: 16px; }
.step-heading > span { font-size: 12px; color: #60756d; }
.workflow-steps { padding: 0; list-style: none; }
.workflow-step { padding: 12px; border: 1px solid #dfe9e5; border-radius: 14px; margin: 16px 0; background: #fbfdfc; }
.workflow-step :deep(.borrow-agent), .workflow-step :deep(.space-agent) { padding: 8px; overflow: visible; }
.workflow-conditions { margin: 18px 0; }
.workflow-conditions fieldset { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; border: 0; padding: 0; }
.workflow-conditions label { display: flex; flex-direction: column; gap: 7px; font-size: 13px; }
.workflow-conditions input { min-width: 0; padding: 10px; border: 1px solid #ceded7; border-radius: 8px; background: white; font: inherit; }
.original-query, .bound-conditions { overflow-wrap: anywhere; }
@media (max-width: 600px) { .workflow-assistant { padding: 18px 12px; } .workflow-conditions fieldset { grid-template-columns: 1fr; } .workflow-step { padding: 8px; } }
</style>
