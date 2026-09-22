<script setup lang="ts">
/**
 * 新增 / 编辑论文弹窗（对应原型的“新增论文”与“编辑论文信息”弹窗）。
 *
 * 本阶段尚未接入后端：保存写入的是内存演示库，因此提交后提示中明确说明“仅在本页
 * 内存中生效”。校验规则与阶段 3 后端保持一致（题目必填、归一后长度 ≥ 8、去重键冲突）。
 */
import { computed, ref, watch } from 'vue'

import { pushToast } from '../composables/useToast'
import { createPaper, DuplicatePaperError, updatePaper } from '../demo/store'
import { NOT_CONNECTED_NOTICE, demoYearLast, demoYears } from '../demo/coverage'
import { allConferences, type Conference, type Paper } from '../types/paper'
import AppModal from './AppModal.vue'

const props = defineProps<{
  open: boolean
  /** 传入论文表示编辑，传 null 表示新增 */
  paper: Paper | null
}>()

const emit = defineEmits<{
  close: []
  saved: [paper: Paper]
}>()

interface FormState {
  code: string
  conference: Conference
  year: number
  title: string
  keywordsText: string
  abstract: string
  landingUrl: string
  pdfUrl: string
}

const form = ref<FormState>(emptyForm())
const errorText = ref('')

function emptyForm(): FormState {
  return {
    code: '',
    conference: 'CVPR',
    year: demoYearLast,
    title: '',
    keywordsText: '',
    abstract: '',
    landingUrl: '',
    pdfUrl: '',
  }
}

const title = computed(() => (props.paper ? '编辑论文信息' : '新增论文'))

watch(
  () => props.open,
  (open) => {
    if (!open) return
    errorText.value = ''
    if (props.paper) {
      form.value = {
        code: props.paper.code,
        conference: props.paper.conference,
        year: props.paper.year,
        title: props.paper.title,
        keywordsText: props.paper.sourceKeywords.join(', '),
        abstract: props.paper.abstract ?? '',
        landingUrl: props.paper.landingUrl ?? '',
        pdfUrl: props.paper.pdfUrl ?? '',
      }
      return
    }
    form.value = emptyForm()
  },
)

function parseKeywords(text: string): string[] {
  return text
    .split(/[,，]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function validate(): string {
  const titleValue = form.value.title.trim()
  if (!titleValue) return '论文题目不能为空，请先填写题目再保存。'
  if (titleValue.length < 8) return '题目过短（少于 8 个字符），请确认是否为完整论文题目。'
  if (!Number.isInteger(form.value.year) || form.value.year <= 0) return '年份必须是有效年份。'
  return ''
}

function onSubmit(): void {
  const message = validate()
  errorText.value = message
  if (message) return

  const payload = {
    title: form.value.title.trim(),
    conference: form.value.conference,
    year: form.value.year,
    abstract: form.value.abstract.trim(),
    sourceKeywords: parseKeywords(form.value.keywordsText),
    landingUrl: form.value.landingUrl.trim(),
    pdfUrl: form.value.pdfUrl.trim(),
  }

  try {
    const saved = props.paper ? updatePaper(props.paper.id, payload) : createPaper(payload)
    const action = props.paper ? '已保存修改' : '已新增 1 篇论文，数据状态为「待复核」'
    pushToast(`${action}。${NOT_CONNECTED_NOTICE}`, 'neutral')
    emit('saved', saved)
    emit('close')
  } catch (error) {
    if (error instanceof DuplicatePaperError) {
      errorText.value = `该论文已存在：${error.existing.code}《${error.existing.title}》。会议、年份与题目相同的记录不允许重复入库。`
      return
    }
    errorText.value = '保存失败，请稍后重试。'
  }
}
</script>

<template>
  <AppModal :open="open" :title="title" width="640px" @close="emit('close')">
    <form class="paper-form" novalidate @submit.prevent="onSubmit">
      <div class="form-grid">
        <div>
          <label class="field-label" for="paper-code">编号（服务端分配，不可修改）</label>
          <input
            id="paper-code"
            class="input code-input"
            type="text"
            :value="form.code || '保存后自动分配'"
            readonly
          />
        </div>
        <div>
          <label class="field-label" for="paper-conference">会议</label>
          <select id="paper-conference" v-model="form.conference" class="select">
            <option v-for="item in allConferences" :key="item" :value="item">{{ item }}</option>
          </select>
        </div>
        <div>
          <label class="field-label" for="paper-year">年份</label>
          <select id="paper-year" v-model.number="form.year" class="select">
            <option v-for="year in demoYears" :key="year" :value="year">{{ year }}</option>
          </select>
        </div>
      </div>

      <div>
        <label class="field-label" for="paper-title">论文题目</label>
        <textarea
          id="paper-title"
          v-model="form.title"
          class="textarea"
          rows="2"
          placeholder="粘贴论文完整题目"
        ></textarea>
      </div>

      <div>
        <label class="field-label" for="paper-keywords">来源关键词（用逗号分隔）</label>
        <input
          id="paper-keywords"
          v-model="form.keywordsText"
          class="input"
          type="text"
          placeholder="目标检测, 视觉语言模型"
        />
        <p class="field-hint">
          作者关键词只用于展示，不参与 Top 10、图谱与趋势统计；系统提取的关键词在采集后生成。
        </p>
      </div>

      <div>
        <label class="field-label" for="paper-abstract">
          摘要（可留空，留空时列表会提示「摘要缺失」）
        </label>
        <textarea
          id="paper-abstract"
          v-model="form.abstract"
          class="textarea"
          rows="3"
          placeholder="用于详情页展示的摘要整理"
        ></textarea>
      </div>

      <div class="form-grid">
        <div>
          <label class="field-label" for="paper-landing">原文入口</label>
          <input
            id="paper-landing"
            v-model="form.landingUrl"
            class="input"
            type="url"
            placeholder="会议论文页地址"
          />
        </div>
        <div>
          <label class="field-label" for="paper-pdf">PDF 地址</label>
          <input
            id="paper-pdf"
            v-model="form.pdfUrl"
            class="input"
            type="url"
            placeholder="https://…"
          />
        </div>
      </div>

      <p v-if="errorText" class="form-error" role="alert">{{ errorText }}</p>
    </form>

    <template #footer>
      <button type="button" class="btn btn-secondary" @click="emit('close')">取消</button>
      <button type="button" class="btn btn-primary" @click="onSubmit">保存</button>
    </template>
  </AppModal>
</template>

<style scoped>
.paper-form {
  display: grid;
  gap: 16px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.code-input {
  background: var(--color-surface-muted);
  color: var(--color-text-subtle);
  font-family: var(--font-mono);
  font-size: 12px;
}

.field-hint {
  margin-top: 6px;
  font-size: 11px;
  color: var(--color-text-faint);
  line-height: 1.6;
}

@media (max-width: 700px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
