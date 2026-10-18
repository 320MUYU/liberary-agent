<script setup>
import { computed, ref, watch } from 'vue'
import BookBorrowAgent from '@/components/BookBorrowAgent.vue'
import SpaceReservationAgent from '@/components/SpaceReservationAgent.vue'
import ConversationAnswer from '@/components/ConversationAnswer.vue'
import { reservationError } from '@/utils/spaceReservation'

const props = defineProps({
  task: { type: Object, required: true },
  busy: Boolean,
  operate: { type: Function, required: true }
})
const error = ref('')
const form = ref({
  date: '',
  start: '',
  end: '',
  people: '',
  purpose: '',
  note: '',
  ...props.task.draft_conditions,
  ...props.task.conditions
})
watch(
  () => JSON.stringify(props.task.draft_conditions),
  (serialized) => {
    const draft = JSON.parse(serialized || '{}')
    form.value = { ...form.value, ...draft }
  },
  { deep: true }
)
const labels = {
  planning: '正在安排',
  ready: '继续处理',
  waiting: '等待你的选择或确认',
  needs_conditions: '请核对预约条件',
  needs_clarification: '请在聊天框补充需求',
  partial_failure: '部分完成',
  retryable: '暂未完成',
  completed: '已完成',
  cancelled: '已停止',
  expired: '已过期',
  budget_exceeded: '已达到执行上限'
}
const finished = computed(() => ['completed', 'cancelled', 'expired'].includes(props.task.status))
const plain = computed(
  () => props.task.steps.length === 1 && props.task.steps[0].result?.status === 'answered'
)
const stepLabels = {
  queued: '待处理',
  running: '处理中',
  waiting: '等待操作',
  completed: '已完成',
  failed: '未完成',
  skipped: '已跳过',
  cancelled: '已取消'
}

async function action(operation, payload = {}) {
  if (props.busy) return
  error.value = ''
  try {
    return await props.operate(props.task.workflow_id, operation, payload)
  } catch (failure) {
    error.value = failure.message || '请求未完成，请刷新状态。'
    throw failure
  }
}
async function conditions() {
  error.value = reservationError(form.value)
  if (error.value) return
  const data = Object.fromEntries(
    ['date', 'start', 'end', 'people', 'purpose', 'note'].map((key) => [key, form.value[key]])
  )
  data.purpose = data.purpose.trim()
  data.note = data.note?.trim() || null
  await action('conditions', { conditions: data }).catch(() => {})
}
function managed(step) {
  return {
    run: step.result,
    busy: props.busy,
    readOnly:
      step.spec.read_only ||
      ['cancelled', 'expired'].includes(props.task.status) ||
      ['skipped', 'cancelled'].includes(step.status),
    operate: async (operation, payload) => {
      const snapshot = await action(operation, { ...payload, step_id: step.id })
      return snapshot?.tasks
        .find((task) => task.workflow_id === props.task.workflow_id)
        ?.steps.find((item) => item.id === step.id)?.result
    }
  }
}
</script>

<template>
  <section
    class="conversation-task"
    :class="{ plain }"
    :aria-label="plain ? '助手回答' : '任务进度与结果'"
  >
    <header v-if="!plain" class="task-heading">
      <strong>{{
        task.steps.length > 1 ? '本次安排' : task.steps[0]?.spec.title || '需求处理'
      }}</strong>
      <span :class="{ complete: task.status === 'completed' }">{{
        labels[task.status] || task.status
      }}</span>
    </header>
    <p v-if="!plain && task.message && !finished" class="task-message">{{ task.message }}</p>
    <p v-if="task.refresh_error" class="task-message" role="alert">{{ task.refresh_error }}</p>
    <p v-if="error" class="card-error" role="alert">{{ error }}</p>
    <form v-if="task.status === 'needs_conditions'" class="conditions" @submit.prevent="conditions">
      <fieldset :disabled="busy">
        <label>日期<input v-model="form.date" type="date" required aria-label="预约日期" /></label>
        <label
          >人数<input
            v-model.number="form.people"
            type="number"
            min="1"
            max="1000"
            required
            aria-label="预约人数"
        /></label>
        <label
          >开始时间<input v-model="form.start" type="time" required aria-label="预约开始时间"
        /></label>
        <label
          >结束时间<input v-model="form.end" type="time" required aria-label="预约结束时间"
        /></label>
        <label
          >用途<input v-model="form.purpose" maxlength="255" required aria-label="预约用途"
        /></label>
        <label>备注<input v-model="form.note" maxlength="200" aria-label="预约备注" /></label>
      </fieldset>
      <p v-if="task.draft_conditions?.date_message">{{ task.draft_conditions.date_message }}</p>
      <div v-if="task.draft_conditions?.date_candidates?.length" class="date-options">
        <el-button
          v-for="candidate in task.draft_conditions.date_candidates"
          :key="candidate.date"
          :disabled="busy"
          @click="form.date = candidate.date"
          >{{ candidate.date }} {{ candidate.weekday }}</el-button
        >
      </div>
      <p>北京时间，至少提前两小时。确认条件后查询空间，提交申请还需再次确认。</p>
      <el-button type="primary" native-type="submit" :disabled="busy">确认查询条件</el-button>
    </form>
    <div v-for="step in task.steps" :key="step.id" class="task-step">
      <div v-if="task.steps.length > 1" class="step-heading">
        <strong>{{ step.position + 1 }}. {{ step.spec.title }}</strong
        ><span>{{ stepLabels[step.status] }}</span>
      </div>
      <template v-if="step.result">
        <ConversationAnswer v-if="step.result.status === 'answered'" :result="step.result" />
        <SpaceReservationAgent
          v-else-if="step.spec.task_type === 'reservation'"
          :managed="managed(step)"
        />
        <BookBorrowAgent v-else :managed="managed(step)" />
      </template>
      <el-button
        v-if="
          !finished &&
          step.id ===
            task.steps.find((item) => !['completed', 'skipped', 'cancelled'].includes(item.status))
              ?.id
        "
        text
        :disabled="busy"
        @click="action('skip', { step_id: step.id }).catch(() => {})"
        >跳过此步骤</el-button
      >
    </div>
    <div v-if="!plain && !finished" class="task-controls">
      <el-button
        v-if="['ready', 'planning', 'partial_failure', 'retryable'].includes(task.status)"
        :disabled="busy"
        @click="action('retry').catch(() => {})"
        >继续未完成步骤</el-button
      >
      <el-button text :disabled="busy" @click="action('cancel').catch(() => {})"
        >停止后续步骤</el-button
      >
    </div>
  </section>
</template>

<style scoped>
.conversation-task {
  margin-top: 10px;
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 18px;
  background: #fff;
  min-width: 0;
}
.conversation-task.plain {
  border: 0;
  padding: 0;
  margin-top: 0;
  background: transparent;
}
.task-heading,
.step-heading {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
}
.task-heading strong {
  color: var(--ink);
  font-size: 15px;
}
.task-heading span,
.step-heading span {
  font-size: 12px;
  color: var(--muted);
}
.task-heading span.complete {
  color: var(--mint-dark);
}
.task-message,
.conditions p {
  font-size: 12px;
  line-height: 1.8;
  color: var(--muted);
  margin: 8px 0;
}
.task-step + .task-step {
  border-top: 1px solid var(--line);
  margin-top: 16px;
  padding-top: 16px;
}
.step-heading {
  margin-bottom: 10px;
}
.task-controls,
.date-options {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 12px;
}
.card-error {
  color: #ad4a3b;
  margin: 10px 0;
}
.conditions fieldset {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  padding: 0;
  margin: 16px 0;
  border: 0;
}
.conditions label {
  display: grid;
  gap: 6px;
  font-size: 12px;
}
.conditions input {
  width: 100%;
  min-width: 0;
  padding: 9px;
  border: 1px solid #d7e1dc;
  border-radius: 8px;
  background: #fff;
}
.task-step :deep(.borrow-agent),
.task-step :deep(.space-agent) {
  padding: 0;
  overflow: visible;
}
@media (max-width: 520px) {
  .conversation-task {
    padding: 12px;
  }
  .conditions fieldset {
    grid-template-columns: 1fr;
  }
}
</style>
