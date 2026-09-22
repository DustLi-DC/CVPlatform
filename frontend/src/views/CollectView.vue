<script setup lang="ts">
/**
 * 页面 4 · 采集与导入（对应原型 04_collect）。
 *
 * 本阶段实现标签页结构、单篇采集表单与结果区状态、批量导入的模板说明、文件选择、
 * 进度与统计区、逐项结果表骨架，以及表单本地校验。
 * 采集与联网、文件解析、任务执行都尚未接入后端，因此相关控件处于明确的待接入状态，
 * 不模拟成功结果，也不显示虚假进度。
 */
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'

import DemoNotice from '../components/DemoNotice.vue'
import EmptyState from '../components/EmptyState.vue'
import PageHeader from '../components/PageHeader.vue'
import StatCard from '../components/StatCard.vue'
import { NOT_CONNECTED_NOTICE } from '../demo/coverage'
import { pushToast } from '../composables/useToast'

const activeTab = ref<'single' | 'batch'>('single')

const singleTitle = ref('')
const singleConference = ref('')
const singleYear = ref('')
const singleError = ref('')

const fileName = ref('')

const canSubmitSingle = computed(() => singleTitle.value.trim().length > 0)

function submitSingle(): void {
  const title = singleTitle.value.trim()
  if (!title) {
    singleError.value = '请先填写论文完整题目。'
    return
  }
  if (title.length < 8) {
    singleError.value = '题目过短（少于 8 个字符），请粘贴会议论文页上的完整题目。'
    return
  }
  singleError.value = ''
  // 采集链路在阶段 5 接入：此处不伪造结果，只说明当前状态
  pushToast('单篇采集尚未接入后端，阶段 5 将实现按题目检索并返回摘要、关键词与原文链接。', 'warning')
}

function onPickFile(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const allowed = ['.csv', '.txt']
  const lower = file.name.toLowerCase()
  if (!allowed.some((extension) => lower.endsWith(extension))) {
    pushToast('仅支持 CSV 与 TXT 文件。', 'warning')
    input.value = ''
    return
  }
  if (file.size > 2 * 1024 * 1024) {
    pushToast('文件超过 2 MB 上限，请拆分后再上传。', 'warning')
    input.value = ''
    return
  }
  fileName.value = file.name
  pushToast('已选择文件。文件解析与任务执行将在阶段 6 接入后端。', 'neutral')
}

function clearFile(): void {
  fileName.value = ''
}
</script>

<template>
  <div>
    <PageHeader
      eyebrow="页面 4 / 论文采集与导入"
      title="补充论文数据"
      description="用完整题目采集单篇论文，或上传 CSV、TXT 列表批量补充。采集与文件解析尚未接入后端，本页当前用于核对界面结构、字段与状态分支。"
    />

    <div class="tab-row">
      <button
        type="button"
        class="tab-btn"
        :class="{ 'is-on': activeTab === 'single' }"
        @click="activeTab = 'single'"
      >
        A. 单篇采集
      </button>
      <button
        type="button"
        class="tab-btn"
        :class="{ 'is-on': activeTab === 'batch' }"
        @click="activeTab = 'batch'"
      >
        B. 批量导入
      </button>
    </div>

    <!-- ============ A. 单篇采集 ============ -->
    <section v-if="activeTab === 'single'" class="collect-grid">
      <div class="card form-card">
        <div class="card-header">
          <div>
            <h2 class="card-title">按完整题目采集</h2>
            <p class="card-subtitle">建议输入会议论文页上的完整英文题目，检索命中率更高。</p>
          </div>
        </div>
        <div class="card-body form-body">
          <div>
            <label class="field-label" for="single-title">论文完整题目</label>
            <textarea
              id="single-title"
              v-model="singleTitle"
              class="textarea"
              rows="3"
              placeholder="例如：Sapiens: Foundation for Human Vision Models"
            ></textarea>
          </div>

          <div class="two-col">
            <div>
              <label class="field-label" for="single-conf">会议（选填）</label>
              <select id="single-conf" v-model="singleConference" class="select">
                <option value="">自动判断</option>
                <option>CVPR</option>
                <option>ICCV</option>
                <option>ECCV</option>
              </select>
            </div>
            <div>
              <label class="field-label" for="single-year">年份（选填）</label>
              <select id="single-year" v-model="singleYear" class="select">
                <option value="">自动判断</option>
                <option v-for="year in [2022, 2023, 2024, 2025]" :key="year" :value="year">
                  {{ year }}
                </option>
              </select>
            </div>
          </div>

          <p v-if="singleError" class="field-error" role="alert">{{ singleError }}</p>

          <button type="button" class="btn btn-primary btn-block" @click="submitSingle">
            开始采集
          </button>

          <DemoNotice tone="info">
            采集链路（查本地 → 未命中再联网 → 候选确认 → 去重入库）在阶段 5 实现，采用超时、限重试与低并发的
            外部请求策略。本页当前只做输入校验，不会发起网络请求。
          </DemoNotice>
        </div>
      </div>

      <div class="card result-card">
        <EmptyState
          title="尚未开始采集"
          description="输入完整题目后点击「开始采集」，这里会显示采集状态与结果。成功结果包含题目、摘要、关键词与原文链接，可直接进入论文详情。"
          boxed
        />
      </div>
    </section>

    <!-- ============ B. 批量导入 ============ -->
    <section v-else class="batch-stack">
      <div class="batch-grid">
        <div class="card">
          <div class="card-header">
            <div>
              <h2 class="card-title">上传论文列表文件</h2>
              <p class="card-subtitle">支持 CSV 与 TXT；单次不超过 500 行、2 MB。</p>
            </div>
          </div>
          <div class="card-body">
            <div class="drop-zone">
              <p class="drop-title">把 CSV / TXT 文件拖到这里，或点击选择文件</p>
              <label class="btn btn-secondary" for="batch-file">选择文件</label>
              <input
                id="batch-file"
                class="visually-hidden"
                type="file"
                accept=".csv,.txt,text/csv,text/plain"
                @change="onPickFile"
              />
            </div>

            <div v-if="fileName" class="file-state">
              <span class="file-name">{{ fileName }}</span>
              <button type="button" class="link-action" @click="clearFile">移除</button>
            </div>

            <DemoNotice class="batch-notice" tone="info">
              文件解析、行校验与后台任务在阶段 6 实现（含 BOM、引号、空行与错误行处理，任务可续跑）。
              当前只校验扩展名与大小，不会解析内容。
            </DemoNotice>
          </div>
        </div>

        <div class="card">
          <div class="card-header">
            <div>
              <h2 class="card-title">模板示例与字段说明</h2>
              <p class="card-subtitle">按模板整理后再上传，可显著减少失败条目。</p>
            </div>
          </div>
          <div class="card-body template-body">
            <div>
              <div class="template-head">
                <span class="template-label">TXT 模板（每行一个论文题目）</span>
                <span class="tag">.txt</span>
              </div>
              <pre class="template-code">High-Resolution Image Synthesis with Latent Diffusion Models
VideoMAE V2: Scaling Video Masked Autoencoders with Dual Masking
Zip-NeRF: Anti-Aliased Grid-Based Neural Radiance Fields</pre>
            </div>

            <div>
              <div class="template-head">
                <span class="template-label">CSV 模板（含 title、conference、year 三列）</span>
                <span class="tag">.csv</span>
              </div>
              <pre class="template-code">title,conference,year
DETRs Beat YOLOs on Real-time Object Detection,CVPR,2024
Segment Anything,ICCV,2023</pre>
            </div>

            <table class="field-table">
              <thead>
                <tr>
                  <th>字段</th>
                  <th>是否必填</th>
                  <th>说明</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td class="mono">title</td>
                  <td>必填</td>
                  <td>论文完整题目，建议使用会议论文页原文</td>
                </tr>
                <tr>
                  <td class="mono">conference</td>
                  <td>选填</td>
                  <td>只能填 CVPR / ICCV / ECCV，留空时按检索结果推断</td>
                </tr>
                <tr>
                  <td class="mono">year</td>
                  <td>选填</td>
                  <td>2022—2025 之间的年份，留空时按检索结果推断</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <section class="card pending-card">
        <div class="card-header">
          <div>
            <h2 class="card-title">处理进度与逐项结果</h2>
            <p class="card-subtitle">
              任务创建后显示总条目数、成功、失败与重复计数，并提供失败重试与重启续跑。
            </p>
          </div>
          <span class="badge badge-neutral">阶段 6 接入</span>
        </div>
        <div class="card-body">
          <div class="stat-grid">
            <StatCard label="总条目数" value="—" hint="等待任务创建" />
            <StatCard label="导入成功" value="—" hint="计数来自任务明细，不做估算" />
            <StatCard label="导入失败" value="—" hint="失败条目可重试，重试仍走去重" />
            <StatCard label="重复条目" value="—" hint="提示已存在的论文编号" />
          </div>
          <EmptyState
            class="pending-empty"
            title="尚未创建导入任务"
            description="任务状态、明细与计数将在阶段 6 由后端接口提供；此处不使用演示进度条模拟处理过程。"
          />
        </div>
      </section>
    </section>
  </div>
</template>

<style scoped>
.tab-row {
  display: flex;
  gap: 8px;
  margin-bottom: 20px;
}

.tab-btn {
  padding: 10px 20px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-text-subtle);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
}

.tab-btn.is-on {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.collect-grid {
  display: grid;
  grid-template-columns: minmax(0, 5fr) minmax(0, 7fr);
  gap: 24px;
  align-items: start;
}

.form-card .form-body {
  display: grid;
  gap: 16px;
}

.two-col {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.result-card {
  padding: 8px;
}

.batch-stack {
  display: grid;
  gap: 24px;
}

.batch-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 24px;
  align-items: start;
}

.drop-zone {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 40px 24px;
  border: 2px dashed var(--color-border-strong);
  border-radius: var(--radius-lg);
  background: var(--color-surface-muted);
  text-align: center;
}

.drop-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-text-muted);
}

.file-state {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 16px;
  padding: 12px 16px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.file-name {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--color-text-muted);
  word-break: break-all;
}

.batch-notice {
  margin-top: 16px;
}

.template-body {
  display: grid;
  gap: 20px;
}

.template-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.template-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-muted);
}

.template-code {
  margin: 0;
  padding: 12px 16px;
  overflow-x: auto;
  border-radius: var(--radius-md);
  background: var(--color-text-strong);
  color: #e2e8f0;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.7;
  white-space: pre;
}

.field-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.field-table th {
  padding-bottom: 8px;
  color: var(--color-text-subtle);
  font-weight: 600;
  text-align: left;
}

.field-table td {
  padding: 8px 0;
  border-top: 1px solid var(--color-border-soft);
  color: var(--color-text-muted);
}

.field-table .mono {
  font-family: var(--font-mono);
  color: var(--color-text);
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.pending-empty {
  margin-top: 16px;
  border: 1px dashed var(--color-border-strong);
  border-radius: var(--radius-lg);
}

@media (max-width: 1200px) {
  .collect-grid,
  .batch-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 700px) {
  .two-col,
  .stat-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
