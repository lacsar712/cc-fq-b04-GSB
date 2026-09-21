<template>
  <q-page class="page-pad">
    <div class="text-h5 q-mb-md">提交质控作业</div>

    <q-banner v-if="auth.role !== 'bioops'" class="bg-warning text-dark q-mb-md" rounded>
      审计员不可提交作业，请使用 bioops 账号。
    </q-banner>

    <q-banner class="bg-info text-white q-mb-md" rounded>
      写死策略：同一样例同日（UTC）仅允许开跑一次，重复提交将被拒绝并留痕；
      自定义纯文本输入不参与该去重。
    </q-banner>

    <q-banner v-if="rejectMessage" class="bg-negative text-white q-mb-md" rounded>
      {{ rejectMessage }}
    </q-banner>

    <q-card flat bordered>
      <q-card-section>
        <div class="text-subtitle1 q-mb-sm">方式一：选择 seed 样例</div>
        <q-select
          v-model="sampleId"
          :options="sampleOptions"
          label="样例"
          outlined
          dense
          clearable
          emit-value
          map-options
          class="q-mb-lg"
        />

        <div class="text-subtitle1 q-mb-sm">方式二：粘贴 FASTQ 文本</div>
        <q-input
          v-model="fastqText"
          type="textarea"
          outlined
          autogrow
          :input-style="{ minHeight: '160px', fontFamily: 'monospace' }"
          hint="规则：首行须以 @ 开头；四行一组（@表头/序列/+/质量串）；不超过 100000 字符；格式错误将由 ParseActor 判为作业失败。若已选样例则优先用样例。"
        />
      </q-card-section>
      <q-card-actions align="right">
        <q-btn flat label="取消" to="/samples" />
        <q-btn
          color="primary"
          label="启动 Actor 流水线"
          :loading="submitting"
          :disable="auth.role !== 'bioops'"
          @click="submit"
        />
      </q-card-actions>
    </q-card>
  </q-page>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { createJob, listSamples } from '../api/client'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const $q = useQuasar()

const samples = ref([])
const sampleId = ref(null)
const fastqText = ref('')
const submitting = ref(false)
// 拒绝/报错横幅：原样展示接口返回的 detail，保证接口与页面同一套说法
const rejectMessage = ref('')

const sampleOptions = computed(() =>
  samples.value.map((s) => ({
    label: `${s.name}（${s.is_broken ? '损坏' : '合格'}）`,
    value: s.id,
  })),
)

async function load() {
  try {
    samples.value = await listSamples()
    const q = route.query.sampleId
    if (q) {
      sampleId.value = Number(q)
    }
  } catch (e) {
    $q.notify({ type: 'negative', message: e.message || '加载样例失败' })
  }
}

async function submit() {
  rejectMessage.value = ''
  if (!sampleId.value && !fastqText.value.trim()) {
    $q.notify({ type: 'warning', message: '请选择样例或粘贴 FASTQ 文本' })
    return
  }
  submitting.value = true
  try {
    const body = sampleId.value
      ? { sampleId: sampleId.value }
      : { fastqText: fastqText.value }
    const job = await createJob(body)
    $q.notify({ type: 'positive', message: `作业 #${job.id} 已创建队` })
    router.push(`/jobs/${job.id}`)
  } catch (e) {
    // 接口文案原样上横幅（含 409 重复开跑拒绝），不另行改写
    rejectMessage.value = e.message || '提交失败'
    $q.notify({ type: 'negative', message: rejectMessage.value })
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>
