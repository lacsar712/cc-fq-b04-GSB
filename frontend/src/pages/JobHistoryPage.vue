<template>
  <q-page class="page-pad">
    <div class="row items-center q-mb-md">
      <div class="text-h5">作业历史</div>
      <q-space />
      <q-btn flat icon="refresh" label="刷新" @click="load" :loading="loading" />
      <q-btn
        v-if="auth.role === 'bioops'"
        color="primary"
        class="q-ml-sm"
        label="新建作业"
        to="/jobs/new"
      />
    </div>

    <q-table
      flat
      bordered
      row-key="id"
      :rows="rows"
      :columns="columns"
      :loading="loading"
      hide-pagination
      :pagination="{ rowsPerPage: 0 }"
    >
      <template #body-cell-status="props">
        <q-td :props="props">
          <q-badge :color="statusColor(props.row.status)">
            {{ statusLabel(props.row.status) }}
          </q-badge>
        </q-td>
      </template>
      <template #body-cell-metrics="props">
        <q-td :props="props">
          <span v-if="props.row.metrics">
            Q={{ props.row.metrics.mean_quality ?? '—' }}
            · N={{ props.row.metrics.n_rate ?? '—' }}
            · reads={{ props.row.metrics.reads ?? '—' }}
          </span>
          <span v-else class="text-grey-6">—</span>
        </q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props">
          <q-btn dense flat color="primary" label="详情" :to="`/jobs/${props.row.id}`" />
        </q-td>
      </template>
    </q-table>

    <div class="row items-center q-mt-lg q-mb-md">
      <div class="text-h6">开跑尝试记录</div>
      <q-space />
      <span class="text-grey-6 text-caption">含被写死策略拒绝的同日重复尝试与越权尝试，可追溯</span>
    </div>

    <q-table
      flat
      bordered
      row-key="id"
      :rows="attemptRows"
      :columns="attemptColumns"
      :loading="loading"
      hide-pagination
      :pagination="{ rowsPerPage: 0 }"
    >
      <template #body-cell-action="props">
        <q-td :props="props">
          <q-badge :color="attemptColor(props.row.action)">
            {{ attemptLabel(props.row.action) }}
          </q-badge>
        </q-td>
      </template>
      <template #body-cell-job_id="props">
        <q-td :props="props">
          <q-btn
            v-if="props.row.job_id"
            dense
            flat
            color="primary"
            :label="`#${props.row.job_id}`"
            :to="`/jobs/${props.row.job_id}`"
          />
          <span v-else class="text-grey-6">—</span>
        </q-td>
      </template>
      <template #body-cell-content_hash="props">
        <q-td :props="props">
          <span v-if="props.value" style="font-family: monospace">{{ props.value.slice(0, 12) }}…</span>
          <span v-else class="text-grey-6">—</span>
        </q-td>
      </template>
    </q-table>
  </q-page>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { listAttempts, listJobs } from '../api/client'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const $q = useQuasar()
const loading = ref(false)
const rows = ref([])
const attemptRows = ref([])

const columns = [
  { name: 'id', label: 'ID', field: 'id', align: 'left' },
  { name: 'sample_name', label: '样例', field: 'sample_name', align: 'left' },
  { name: 'status', label: '状态', field: 'status', align: 'left' },
  { name: 'created_by', label: '提交人', field: 'created_by', align: 'left' },
  { name: 'metrics', label: '指标摘要', field: 'metrics', align: 'left' },
  {
    name: 'created_at',
    label: '创建时间',
    field: 'created_at',
    align: 'left',
    format: (v) => (v ? new Date(v).toLocaleString() : ''),
  },
  { name: 'actions', label: '操作', field: 'actions', align: 'left' },
]

const attemptColumns = [
  { name: 'id', label: 'ID', field: 'id', align: 'left' },
  {
    name: 'created_at',
    label: '时间',
    field: 'created_at',
    align: 'left',
    format: (v) => (v ? new Date(v).toLocaleString() : ''),
  },
  { name: 'username', label: '用户', field: 'username', align: 'left' },
  { name: 'role', label: '角色', field: 'role', align: 'left' },
  { name: 'sample_name', label: '样例', field: 'sample_name', align: 'left' },
  { name: 'content_hash', label: '文本指纹', field: 'content_hash', align: 'left' },
  { name: 'action', label: '结果', field: 'action', align: 'left' },
  { name: 'job_id', label: '关联作业', field: 'job_id', align: 'left' },
  { name: 'detail', label: '说明', field: 'detail', align: 'left' },
]

function attemptLabel(a) {
  return (
    {
      created: '已开跑',
      rejected_duplicate: '同日重复被拒',
      rejected_forbidden: '越权被拒',
    }[a] || a
  )
}

function attemptColor(a) {
  return (
    {
      created: 'positive',
      rejected_duplicate: 'warning',
      rejected_forbidden: 'negative',
    }[a] || 'grey'
  )
}

function statusLabel(s) {
  return { pending: '排队中', running: '运行中', success: '成功', failed: '失败' }[s] || s
}

function statusColor(s) {
  return { pending: 'grey', running: 'info', success: 'positive', failed: 'negative' }[s] || 'grey'
}

async function load() {
  loading.value = true
  try {
    const [jobs, attempts] = await Promise.all([listJobs(), listAttempts()])
    rows.value = jobs
    attemptRows.value = attempts
  } catch (e) {
    $q.notify({ type: 'negative', message: e.message || '加载失败' })
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
