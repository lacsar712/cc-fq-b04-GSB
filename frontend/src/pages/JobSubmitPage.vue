<template>
  <q-page class="page-pad">
    <div class="text-h5 q-mb-md">提交质控作业</div>

    <q-banner v-if="auth.role !== 'bioops'" class="bg-warning text-dark q-mb-md" rounded>
      审计员不可提交作业，请使用 bioops 账号。
    </q-banner>

    <q-banner class="bg-info text-dark q-mb-md" rounded>
      写死策略：同一样例（或相同自定义文本）同一自然日（UTC）仅允许开跑一次，
      重复提交将被接口拒绝（409）并记录，可在「作业历史」页的尝试记录中追溯。
    </q-banner>

    <q-banner v-if="duplicateError" class="bg-negative text-white q-mb-md" rounded>
      <div>{{ duplicateError.message }}</div>
      <template #action>
        <q-btn
          flat
          color="white"
          :label="`查看已有作业 #${duplicateError.existingJobId}`"
          :to="`/jobs/${duplicateError.existingJobId}`"
        />
      </template>
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
          hint="四行一组：@header / 序列 / + / 质量串。若已选样例则优先用样例。相同文本同日重复提交会被拒绝。"
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
import { computed, onMounted, ref, watch } from 'vue'
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
const duplicateError = ref(null)

const sampleOptions = computed(() =>
  samples.value.map((s) => ({
    label: `${s.name}（${s.is_broken ? '损坏' : '合格'}）`,
    value: s.id,
  })),
)

// 输入变化时清掉上一次的重复拒绝提示
watch([sampleId, fastqText], () => {
  duplicateError.value = null
})

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
  if (!sampleId.value && !fastqText.value.trim()) {
    $q.notify({ type: 'warning', message: '请选择样例或粘贴 FASTQ 文本' })
    return
  }
  submitting.value = true
  duplicateError.value = null
  try {
    const body = sampleId.value
      ? { sampleId: sampleId.value }
      : { fastqText: fastqText.value }
    const job = await createJob(body)
    $q.notify({ type: 'positive', message: `作业 #${job.id} 已创建队` })
    router.push(`/jobs/${job.id}`)
  } catch (e) {
    if (e.detail?.code === 'duplicate_same_day') {
      // 与接口同一套说法：原样展示接口返回的 message
      duplicateError.value = {
        message: e.message,
        existingJobId: e.detail.existingJobId,
      }
    } else {
      $q.notify({ type: 'negative', message: e.message || '提交失败' })
    }
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>
