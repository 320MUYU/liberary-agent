<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { addBooking, labs } from '@/store/labStore'

const props = defineProps({ modelValue: Boolean, selectedLab: { type: Object, default: null } })
const emit = defineEmits(['update:modelValue', 'success'])
const formRef = ref()
const submitting = ref(false)
function localToday() {
  const date = new Date()
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}
const form = reactive({ labId: '', date: localToday(), start: '14:00', end: '16:00', people: 1, purpose: '', note: '' })

const selected = computed(() => labs.find((item) => item.id === Number(form.labId)))
const rules = {
  labId: [{ required: true, message: '请选择实验室', trigger: 'change' }],
  date: [{ required: true, message: '请选择预约日期', trigger: 'change' }],
  purpose: [{ required: true, message: '请填写实验用途', trigger: 'blur' }],
}

watch(() => props.modelValue, (open) => {
  if (open && props.selectedLab) form.labId = props.selectedLab.id
})

function disabledDate(date) { return date.getTime() < new Date(`${localToday()}T00:00:00`).getTime() }

async function submit() {
  await formRef.value.validate()
  if (form.start >= form.end) return ElMessage.warning('结束时间需要晚于开始时间')
  submitting.value = true
  try {
    const booking = await addBooking({ ...form, labId: Number(form.labId) })
    emit('update:modelValue', false)
    emit('success', booking)
    ElMessage.success('预约申请已提交，请等待管理员审核')
    form.purpose = ''
    form.note = ''
  } catch {
    // 接口层已显示失败原因，保留表单内容方便修改后重试。
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog :model-value="modelValue" width="min(620px, 92vw)" title="提交实验室预约" @update:model-value="emit('update:modelValue', $event)">
    <div class="dialog-intro">
      <span><el-icon><Calendar /></el-icon></span>
      <div><strong>填写预约信息</strong><p>申请提交后将由实验室管理员审核，请确保信息真实完整。</p></div>
    </div>
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="booking-form">
      <el-form-item label="实验室" prop="labId">
        <el-select v-model="form.labId" placeholder="选择实验室" style="width: 100%">
          <el-option v-for="lab in labs.filter((item) => item.status !== 'maintenance')" :key="lab.id" :label="`${lab.name} · ${lab.code}`" :value="lab.id" />
        </el-select>
      </el-form-item>
      <div v-if="selected" class="lab-summary"><el-icon><Location /></el-icon>{{ selected.building }} · {{ selected.code }}<span></span><el-icon><User /></el-icon>容纳 {{ selected.capacity }} 人</div>
      <div class="form-grid three">
        <el-form-item label="预约日期" prop="date"><el-date-picker v-model="form.date" type="date" value-format="YYYY-MM-DD" :disabled-date="disabledDate" style="width: 100%" /></el-form-item>
        <el-form-item label="开始时间"><el-time-select v-model="form.start" start="08:00" step="00:30" end="21:00" style="width: 100%" /></el-form-item>
        <el-form-item label="结束时间"><el-time-select v-model="form.end" start="08:30" step="00:30" end="22:00" style="width: 100%" /></el-form-item>
      </div>
      <div class="form-grid">
        <el-form-item label="实验人数"><el-input-number v-model="form.people" :min="1" :max="selected?.capacity || 50" style="width: 100%" /></el-form-item>
        <el-form-item label="实验用途" prop="purpose"><el-input v-model="form.purpose" placeholder="例如：课程实验 / 项目测试" /></el-form-item>
      </div>
      <el-form-item label="补充说明（选填）"><el-input v-model="form.note" type="textarea" :rows="3" placeholder="可说明所需设备、软件环境或其他要求" maxlength="200" show-word-limit /></el-form-item>
    </el-form>
    <template #footer><el-button @click="emit('update:modelValue', false)">取消</el-button><el-button type="primary" :loading="submitting" @click="submit">提交预约申请</el-button></template>
  </el-dialog>
</template>

<style scoped>
.dialog-intro { display: flex; gap: 12px; margin: -6px 0 23px; padding: 14px 16px; background: #edf6f3; border-radius: 11px; }
.dialog-intro > span { width: 34px; height: 34px; display: grid; place-items: center; flex: none; color: white; background: var(--mint-dark); border-radius: 9px; }
.dialog-intro strong { color: var(--ink); font-size: 12px; }.dialog-intro p { margin-top: 3px; color: #768885; font-size: 10px; }
.booking-form :deep(.el-form-item__label) { color: #3d5654; font-size: 11px; font-weight: 700; }
.lab-summary { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin: -10px 0 18px; padding: 8px 10px; color: #6e817f; font-size: 10px; background: #fafaf7; border: 1px solid #ecece6; border-radius: 8px; }
.lab-summary span { width: 1px; height: 11px; margin: 0 5px; background: #dfe3dd; }
.form-grid { display: grid; grid-template-columns: 1fr 2fr; gap: 14px; }.form-grid.three { grid-template-columns: 1.4fr 1fr 1fr; }
@media (max-width: 600px) { .form-grid, .form-grid.three { grid-template-columns: 1fr; gap: 0; } }
</style>
