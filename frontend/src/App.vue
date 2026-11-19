<script setup>
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { api } from './api'

const messages = ref([])
const input = ref('')
const sending = ref(false)
const tab = ref('memories')

const memories = ref([])
const stats = ref({ total: 0, by_category: {} })
const conflicts = ref([])
const metrics = ref({ requests_total: 0, errors_total: 0, latency_p50_ms: 0, latency_p95_ms: 0, llm_failures: 0 })
const health = ref({ status: 'unknown', db: '-', llm: '-' })
const lastUsed = ref([])
const lastWritten = ref([])
const errorMsg = ref('')

const threadEl = ref(null)

const catColor = {
  identity: '#4ea1ff',
  preference: '#9b7bff',
  goal: '#33d29a',
  relation: '#ff9f43',
  event: '#ff6b8a',
}

const catLabel = {
  identity: '身份',
  preference: '偏好',
  goal: '目标',
  relation: '关系',
  event: '事件',
}

const statusDot = computed(() => (health.value.status === 'ok' ? 'ok' : 'warn'))

const totalTokensSaved = computed(() => {
  const n = stats.value.total || 0
  return n ? `${n} 条记忆 ≈ 每轮省 ${Math.max(0, n * 18)} token` : '-'
})

async function refreshAll() {
  try {
    const [mem, cfg, met, hea] = await Promise.all([
      api.memories(200),
      api.conflicts(20),
      api.metrics(),
      api.health(),
    ])
    memories.value = mem.items
    stats.value = { total: mem.total, by_category: mem.by_category }
    conflicts.value = cfg.items
    metrics.value = met
    health.value = hea
  } catch (e) {
    errorMsg.value = String(e.message || e)
  }
}

async function send() {
  const text = input.value.trim()
  if (!text || sending.value) return
  input.value = ''
  messages.value.push({ role: 'user', text })
  sending.value = true
  errorMsg.value = ''
  try {
    const res = await api.chat(text)
    messages.value.push({
      role: 'assistant',
      text: res.answer,
      used: res.used,
      refused: res.refused,
      latency: res.latency_ms,
    })
    lastUsed.value = res.used
    lastWritten.value = res.written
    await refreshAll()
  } catch (e) {
    messages.value.push({ role: 'assistant', text: `请求失败：${e.message}`, refused: true })
  } finally {
    sending.value = false
    await scrollBottom()
  }
}

async function scrollBottom() {
  await nextTick()
  if (threadEl.value) threadEl.value.scrollTop = threadEl.value.scrollHeight
}

async function del(id) {
  try {
    await api.remove(id)
    await refreshAll()
  } catch (e) {
    errorMsg.value = String(e.message || e)
  }
}

watch(tab, (v) => {
  if (v === 'conflicts') api.conflicts(30).then((r) => (conflicts.value = r.items)).catch(() => {})
  if (v === 'metrics') api.metrics().then((r) => (metrics.value = r)).catch(() => {})
})

onMounted(async () => {
  await refreshAll()
  setInterval(refreshAll, 15000)
})
</script>

<template>
  <div class="shell">
    <header class="top">
      <div class="brand">
        <div class="logo">M</div>
        <div>
          <h1>MemKeep</h1>
          <p>Agent 长期记忆 · 抽取 / 冲突消解 / 检索 / 作答</p>
        </div>
      </div>
      <div class="top-stats">
        <span class="pill" :class="statusDot">{{ health.status === 'ok' ? '在线' : '降级' }}</span>
        <span class="pill">库 {{ health.db === 'ok' ? '正常' : '异常' }}</span>
        <span class="pill">模型 {{ health.llm === 'ok' ? '正常' : '异常' }}</span>
        <span class="pill">记忆 {{ stats.total }}</span>
        <span class="pill">P95 {{ metrics.latency_p95_ms }}ms</span>
      </div>
    </header>

    <main class="body">
      <section class="chat">
        <div class="thread" ref="threadEl">
          <div v-if="!messages.length" class="empty">
            <h2>问它记住了什么</h2>
            <p>试试：「我投了哪些公司？」「我讨厌什么样的工作？」「我养宠物吗？」</p>
            <div class="chips">
              <button @click="input = '我投了哪些公司？'">投了哪些公司</button>
              <button @click="input = '我讨厌什么样的工作？'">讨厌什么工作</button>
              <button @click="input = '搜狐二面为什么没过？'">搜狐为何被挂</button>
            </div>
          </div>

          <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
            <div class="bubble" :class="{ refused: m.refused }">{{ m.text }}</div>
            <div v-if="m.used && m.used.length" class="used">
              <span v-for="u in m.used" :key="u.id" class="tag" :style="{ borderColor: catColor[u.category] }">
                {{ u.attribute }} · {{ u.score }}
              </span>
              <span class="lat">{{ m.latency }}ms</span>
            </div>
          </div>

          <div v-if="sending" class="msg assistant">
            <div class="bubble typing"><i></i><i></i><i></i></div>
          </div>
        </div>

        <div class="composer">
          <input
            v-model="input"
            placeholder="说点什么，或问它记住了什么"
            @keyup.enter="send"
            :disabled="sending"
          />
          <button @click="send" :disabled="sending || !input.trim()">发送</button>
        </div>
        <div v-if="errorMsg" class="err">{{ errorMsg }}</div>
      </section>

      <section class="panel">
        <div class="tabs">
          <button :class="{ on: tab === 'memories' }" @click="tab = 'memories'">记忆 {{ stats.total }}</button>
          <button :class="{ on: tab === 'conflicts' }" @click="tab = 'conflicts'">冲突 {{ conflicts.length }}</button>
          <button :class="{ on: tab === 'metrics' }" @click="tab = 'metrics'">指标</button>
        </div>

        <div v-if="tab === 'memories'" class="pane">
          <div class="cats">
            <span v-for="(n, c) in stats.by_category" :key="c" class="cat">
              <i :style="{ background: catColor[c] }"></i>{{ catLabel[c] || c }} {{ n }}
            </span>
          </div>
          <ul class="list">
            <li v-for="m in memories" :key="m.id" class="item">
              <div class="item-head">
                <span class="badge" :style="{ color: catColor[m.category] }">{{ catLabel[m.category] || m.category }}</span>
                <span class="attr">{{ m.attribute }}</span>
                <span class="score">{{ m.score.toFixed(2) }}</span>
                <button class="del" @click="del(m.id)">删</button>
              </div>
              <p class="val">{{ m.value }}</p>
              <div class="bar"><span :style="{ width: Math.min(100, m.score * 60) + '%', background: catColor[m.category] }"></span></div>
            </li>
          </ul>
          <p v-if="!memories.length" class="empty-text">还没有记忆，先在左边聊两句。</p>
        </div>

        <div v-else-if="tab === 'conflicts'" class="pane">
          <ul class="list">
            <li v-for="c in conflicts" :key="c.id" class="item">
              <div class="item-head">
                <span class="badge" :style="{ color: c.resolution === 'update' ? '#ff9f43' : '#4ea1ff' }">
                  {{ c.resolution === 'update' ? '覆盖' : '共存' }}
                </span>
                <span class="attr">#{{ c.old_id }} → #{{ c.new_id }}</span>
              </div>
              <p class="val">{{ c.reason || '未记录原因' }}</p>
            </li>
          </ul>
          <p v-if="!conflicts.length" class="empty-text">还没有冲突记录。</p>
        </div>

        <div v-else class="pane">
          <div class="metric-grid">
            <div class="metric"><span>请求数</span><b>{{ metrics.requests_total }}</b></div>
            <div class="metric"><span>错误数</span><b>{{ metrics.errors_total }}</b></div>
            <div class="metric"><span>P50</span><b>{{ metrics.latency_p50_ms }}ms</b></div>
            <div class="metric"><span>P95</span><b>{{ metrics.latency_p95_ms }}ms</b></div>
            <div class="metric"><span>模型失败</span><b>{{ metrics.llm_failures }}</b></div>
            <div class="metric"><span>记忆总量</span><b>{{ stats.total }}</b></div>
          </div>
          <p class="hint">{{ totalTokensSaved }}</p>
        </div>
      </section>
    </main>
  </div>
</template>
