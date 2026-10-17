<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { getUserInfo } from '@/auth'
import {
  startBorrowRun,
  getBorrowRun,
  selectReservationSpace,
  getSpacePage,
  decideBorrow,
  retryBorrowRun
} from '@/api/agentApi'
import {
  reservationError,
  spaceAvailability,
  reservationHeading,
  formatSpaceTime
} from '@/utils/spaceReservation'

const props = defineProps({ managed: { type: Object, default: null } })
const form = ref(props.managed?.run?.conditions || { date: '', start: '', end: '', people: 1, purpose: '', note: '' })
const query = ref('')
const run = ref(props.managed?.run || null)
const busy = ref(false)
const error = ref('')
const storageKey = `space-reservation-run-${getUserInfo()?.id}`
const runId = ref(props.managed ? props.managed.run?.run_id || '' : sessionStorage.getItem(storageKey) || '')
watch(() => props.managed?.run, (value) => {
  if (!value) return
  run.value = value
  runId.value = value.run_id
  if (value.conditions) form.value = { ...value.conditions, note: value.conditions.note || '' }
})
let active = true
onUnmounted(() => {
  active = false
})

async function perform(operation, kind, payload) {
  if (busy.value || props.managed?.busy) return
  busy.value = true
  error.value = ''
  try {
    const result = await (props.managed && kind ? props.managed.operate(kind, payload) : operation())
    if (active) {
      run.value = result
      if (result.conditions)
        form.value = { ...result.conditions, note: result.conditions.note || '' }
    }
  } catch (failure) {
    if (active) error.value = failure.message || '请求未完成，请刷新任务状态。'
  } finally {
    if (active) busy.value = false
  }
}

async function search() {
  if (props.managed) return
  if (busy.value || runId.value) return
  error.value = reservationError(form.value)
  if (error.value) return
  if (query.value.trim().length > 1000) {
    error.value = '空间需求不能超过1000字。'
    return
  }
  runId.value = crypto.randomUUID()
  sessionStorage.setItem(storageKey, runId.value)
  await perform(() =>
    startBorrowRun({
      request_id: runId.value,
      task_type: 'reservation',
      query: query.value.trim() || '查询符合人数和指定时段的学习空间，供我选择',
      conditions: {
        ...form.value,
        purpose: form.value.purpose.trim(),
        note: form.value.note.trim() || null
      }
    })
  )
}

async function selectSpace(id) {
  if (props.managed?.readOnly) return
  if (
    run.value?.status !== 'select_space' ||
    !run.value.spaces.some((space) => space.id === id && space.can_reserve)
  )
    return
  await perform(() => selectReservationSpace(runId.value, id), 'select_space', { space_id: id })
}

async function changePage(page) {
  if (run.value?.status !== 'select_space') return
  await perform(() => getSpacePage(runId.value, page), 'spaces_page', { page })
}

async function decide(confirmed) {
  if (props.managed?.readOnly) return
  if (run.value?.status !== 'confirm_reservation') return
  const payload = { action_id: run.value.action.id, confirmed }
  await perform(() => decideBorrow(runId.value, payload), 'decision', payload)
}

async function refresh() {
  if (runId.value && !props.managed) await perform(() => getBorrowRun(runId.value))
}

async function retry() {
  if (runId.value) await perform(() => retryBorrowRun(runId.value), 'retry')
}

async function restart() {
  if (props.managed) return
  if (busy.value) return
  if (run.value?.status === 'confirm_reservation') {
    await decide(false)
    if (run.value?.status !== 'cancelled') return
  }
  run.value = null
  runId.value = ''
  error.value = ''
  sessionStorage.removeItem(storageKey)
}

onMounted(refresh)
</script>

<template>
  <div class="space-agent">
    <div v-if="!props.managed" class="space-intro">
      <span>学习空间 · 指定时段查询</span>
      <h3>为这次学习，找一个合适的空间</h3>
      <p>填写明确条件，查询实际空间。选择并确认后才提交预约，最终由管理员审核。</p>
    </div>
    <form v-if="!props.managed" class="space-form" @submit.prevent="search">
      <fieldset :disabled="busy || !!runId">
        <label class="wide"
          >空间需求（可选）<el-input
            v-model="query"
            maxlength="1000"
            placeholder="例如：找一个有投影仪的研讨室"
        /></label>
        <label
          >预约日期<input v-model="form.date" type="date" required aria-label="预约日期"
        /></label>
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
          >开始时间<input v-model="form.start" type="time" required aria-label="开始时间"
        /></label>
        <label
          >结束时间<input v-model="form.end" type="time" required aria-label="结束时间"
        /></label>
        <label class="wide"
          >使用用途<el-input
            v-model="form.purpose"
            maxlength="255"
            placeholder="例如：小组课程讨论"
            aria-label="使用用途"
        /></label>
        <label class="wide"
          >备注（可选）<el-input v-model="form.note" maxlength="200" aria-label="预约备注"
        /></label>
      </fieldset>
      <p class="muted">
        时间均为北京时间；需至少提前两小时，同一次预约不能跨天。待审核申请不锁定时段。
      </p>
      <el-button type="primary" native-type="submit" :loading="busy" :disabled="!!runId"
        >查询空间</el-button
      >
    </form>
    <p v-if="busy" role="status">正在处理，请稍候…</p>
    <el-alert v-if="error" :title="error" type="warning" :closable="false" show-icon />
    <div v-if="runId && !props.managed" class="space-controls">
      <el-button :disabled="busy" @click="refresh">刷新任务状态</el-button>
      <el-button
        v-if="error || run?.status === 'retryable' || run?.status === 'confirmed'"
        :disabled="busy"
        @click="retry"
        >继续未完成任务</el-button
      >
      <el-button :disabled="busy" @click="restart">开始新任务</el-button>
    </div>
    <section v-if="run?.status === 'select_space'" aria-label="可选空间">
      <p>{{ props.managed?.readOnly ? '本步仅查询，未提交预约。' : run.message }}</p>
      <p class="muted">
        检查时间：{{ formatSpaceTime(run.checked_at) }}。刷新可重查本页，提交时再次校验。
      </p>
      <el-empty v-if="!run.spaces.length" description="没有匹配空间，可开始新任务调整需求。" />
      <div class="space-cards">
        <article v-for="space in run.spaces" :key="space.id" class="space-card">
          <h4>{{ space.name }} · {{ space.code }}</h4>
          <p>{{ space.building }} · {{ space.floor }} 层 · {{ space.category }}</p>
          <p>容量 {{ space.capacity }} 人 · 本次 {{ form.people }} 人</p>
          <p v-if="space.equipments?.length" class="facilities">
            <span v-for="(equipment, index) in space.equipments" :key="index"
              >{{ equipment.name }}：{{
                equipment.status === 'normal' ? `登记可用 ${equipment.available}` : '维修或停用'
              }}</span
            >
          </p>
          <p v-else class="muted">未登记设施</p>
          <p class="availability">{{ spaceAvailability(space) }}</p>
          <el-button
            v-if="!props.managed?.readOnly"
            type="primary"
            :disabled="busy || props.managed?.busy || !space.can_reserve"
            @click="selectSpace(space.id)"
            >选择这个空间</el-button
          >
        </article>
      </div>
      <el-pagination
        v-if="run.total > run.page_size"
        layout="prev, pager, next"
        :current-page="run.page"
        :page-size="run.page_size"
        :total="run.total"
        :pager-count="5"
        :disabled="busy"
        @current-change="changePage"
      />
    </section>
    <section
      v-if="run?.status === 'confirm_reservation'"
      class="space-confirm"
      aria-label="确认空间预约"
    >
      <span class="eyebrow">请核对本次预约</span>
      <h3>{{ run.action.space.name }} · {{ run.action.space.code }}</h3>
      <p>
        {{ run.action.space.building }} · {{ run.action.space.floor }} 层 · 容量
        {{ run.action.space.capacity }} 人
      </p>
      <p class="slot">
        {{ run.action.conditions.date }} {{ run.action.conditions.start }}—{{
          run.action.conditions.end
        }}（北京时间）
      </p>
      <p>预约人数：{{ run.action.conditions.people }} 人</p>
      <p>用途：{{ run.action.conditions.purpose }}</p>
      <p v-if="run.action.conditions.note">备注：{{ run.action.conditions.note }}</p>
      <p>{{ run.action.message }}</p>
      <p class="muted">
        确认有效至 {{ formatSpaceTime(run.action.expires_at) }}；信息变化后需重新查询。
      </p>
      <div class="space-controls">
        <el-button type="primary" :disabled="busy" @click="decide(true)">确认提交预约</el-button>
        <el-button :disabled="busy" @click="decide(false)">取消本次操作</el-button>
      </div>
    </section>
    <section
      v-if="run?.status?.startsWith('reservation_') || run?.status === 'cancelled'"
      class="space-result"
      aria-label="预约结果"
    >
      <h3>{{ reservationHeading(run.status) }}</h3>
      <p>{{ run.message }}</p>
      <template v-if="run.receipt?.reservation">
        <p>预约编号 #{{ run.receipt.reservation_id }} · {{ run.receipt.reservation.lab_name }}</p>
        <p>
          {{ run.receipt.reservation.date }} {{ run.receipt.reservation.start }}—{{
            run.receipt.reservation.end
          }}
        </p>
        <p v-if="run.receipt.reservation.review_note">
          审核说明：{{ run.receipt.reservation.review_note }}
        </p>
      </template>
      <router-link to="/reservations">前往我的预约</router-link>
    </section>
    <p v-if="['no_results', 'tool_unavailable'].includes(run?.status)" role="status">
      {{ run.message }}
    </p>
  </div>
</template>

<style scoped>
.space-agent {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 26px;
  color: var(--ink);
}
.space-intro span,
.eyebrow {
  color: var(--gold-700);
  font-size: 12px;
}
.space-intro h3 {
  font-size: 22px;
  margin: 10px 0;
}
.space-agent p {
  font-size: 13px;
  line-height: 1.8;
  margin: 8px 0;
  overflow-wrap: anywhere;
}
.space-form {
  margin: 22px 0;
}
.space-form fieldset {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  padding: 0;
  border: 0;
  min-width: 0;
}
.space-form label {
  display: grid;
  gap: 6px;
  font-size: 12px;
  min-width: 0;
}
.space-form .wide {
  grid-column: 1 / -1;
}
.space-form input {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  padding: 9px 10px;
  border: 1px solid #d7dfe4;
  border-radius: 6px;
  font: inherit;
  background: white;
  color: var(--ink);
}
.space-form input:disabled {
  background: #f3f5f6;
  color: #687b87;
}
.space-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 16px 0;
}
.space-controls :deep(.el-button + .el-button) {
  margin-left: 0;
}
.space-cards {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin: 16px 0;
}
.space-card {
  border: 1px solid #dce3e7;
  border-radius: 12px;
  padding: 18px;
  min-width: 0;
}
.space-card h4 {
  font-size: 16px;
  overflow-wrap: anywhere;
}
.facilities {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  color: #5d6e79;
}
.availability {
  color: var(--navy-800);
  font-weight: 600;
}
.space-confirm,
.space-result {
  padding: 22px;
  border: 1px solid #e6d5b4;
  border-radius: 12px;
  background: #fcfaf5;
  margin: 18px 0;
}
.space-confirm h3,
.space-result h3 {
  font-size: 19px;
  margin: 9px 0;
  overflow-wrap: anywhere;
}
.slot {
  font-weight: 600;
}
.space-agent .muted {
  color: #687d88;
  font-size: 12px;
}
.space-result a {
  display: inline-block;
  margin-top: 12px;
  color: var(--navy-800);
}
@media (max-width: 600px) {
  .space-agent {
    padding: 16px;
  }
  .space-intro h3 {
    font-size: 19px;
  }
  .space-cards {
    grid-template-columns: 1fr;
  }
  .space-confirm,
  .space-result {
    padding: 16px;
  }
}
</style>
