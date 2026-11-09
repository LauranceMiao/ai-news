<template>
  <div class="page">
    <h1 class="hero-title">精选</h1>
    <p class="hero-sub" v-if="updatedAt">数据更新于 {{ updatedAt }}</p>

    <div class="filter-row">
      <div class="chips">
        <button
          v-for="category in displayCategories"
          :key="category.id"
          class="chip"
          :class="{ active: category.id === activeCategory }"
          @click="switchCategory(category)"
        >
          {{ category.name }}
        </button>
      </div>

      <button class="ghost-btn refresh-btn" :disabled="refreshingLive" @click="onRefresh">
        {{ refreshingLive ? '刷新中…' : '刷新' }}
      </button>

      <div class="search-wrap">
        <input
          v-model="keyword"
          class="search-input"
          placeholder="搜索标题、摘要…"
          @keyup.enter="doSearch"
        />
        <span class="search-key">/</span>
      </div>
    </div>

    <!-- 搜索结果 -->
    <template v-if="searchMode">
      <div class="block-head">
        <span>「{{ activeKeyword }}」找到 {{ searchResults.length }} 条{{ searchModeText }}</span>
        <button class="link-more" @click="clearSearch">退出搜索 →</button>
      </div>
      <article
        v-for="item in searchResults"
        :key="item.id"
        class="feed-card"
        @click="goDetail(item.id)"
      >
        <div class="feed-meta">
          <span class="src">{{ item.source || '新闻' }}</span>
          <span class="badge-tag">相关</span>
          <span class="spacer"></span>
          <span v-if="item.score" class="badge-score">相关度 | {{ Math.round(item.score * 100) }}</span>
        </div>
        <h3 class="feed-title">{{ item.title }}</h3>
        <p class="feed-desc">{{ item.description }}</p>
      </article>
    </template>

    <template v-else>
      <!-- 今日要闻（替代参考站的「当前热点」卡位） -->
      <section class="hot-panel" v-if="daily">
        <div class="hot-head">
          <span class="hot-dot"></span>
          <span class="hot-name">今日要闻</span>
          <span class="spacer"></span>
          <span class="hot-date">{{ daily.date }}</span>
        </div>
        <div class="hot-body" v-show="dailyOpen">{{ daily.content }}</div>
        <div class="hot-foot" v-show="dailyOpen">
          <span
            v-for="ref in dailyRefs"
            :key="ref.newsId"
            class="hot-ref"
            @click="goDetail(ref.newsId)"
          >
            [{{ ref.no }}] {{ ref.title }}
          </span>
          <button class="link-more" @click="dailyOpen = !dailyOpen">
            {{ dailyOpen ? '收起' : '展开' }}
          </button>
        </div>
      </section>

      <!-- 日期分组的新闻流 -->
      <section v-for="group in groups" :key="group.date" class="day-block">
        <div class="day-head">
          <h2 class="day-title">{{ group.label }}</h2>
          <span class="day-sub">{{ group.weekday }} · {{ group.items.length }} 条</span>
          <span class="spacer"></span>
          <button class="ghost-btn" :class="{ on: readOnly }" @click="toggleReadOnly">
            {{ readOnly ? '查看全部' : '只看未读' }}
          </button>
        </div>

        <article
          v-for="item in group.items"
          :key="item.id"
          class="feed-row"
          @click="goDetail(item.id)"
        >
          <div class="time-col">
            <span class="time-text">{{ timeOf(item) }}</span>
            <i class="time-dot" :class="{ read: isRead(item.id) }"></i>
          </div>

          <div class="feed-card">
            <div class="feed-meta">
              <span class="src">{{ item.source || '新闻' }}</span>
              <span class="badge-tag">精选</span>
              <span class="spacer"></span>
              <span class="badge-score">AI 评分 | {{ aiScore(item) }}</span>
            </div>
            <h3 class="feed-title">{{ item.title }}</h3>
            <p class="feed-desc">{{ item.description }}</p>
            <div class="reason">
              <span class="reason-label">推荐理由：</span>
              来自 {{ item.source || '站内' }}，{{ item.publishTime }} 发布，已有 {{ item.views || 0 }} 次阅读。
            </div>
          </div>
        </article>
      </section>

      <div class="list-foot">
        <button v-if="newsStore.loading" class="ghost-btn" disabled>加载中…</button>
        <button v-else-if="!newsStore.finished" class="ghost-btn" @click="onLoad">加载更多</button>
        <span v-else class="foot-text">已经到底了</span>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useNewsStore } from '../store/modules/news'
import { apiConfig, aiConfig } from '../config/api'
import { showToast } from 'vant'
import { getReadIds } from '../utils/readState'

const router = useRouter()
const route = useRoute()
const newsStore = useNewsStore()

const keyword = ref('')
const activeKeyword = ref('')
const searchMode = ref(false)
const searching = ref(false)
const searchResults = ref([])
const searchModeText = ref('')

const activeCategory = ref(null)
const refreshingLive = ref(false)
const readOnly = ref(false)
const readIds = ref(getReadIds())
const updatedAt = ref('')

const daily = ref(null)
const dailyOpen = ref(true)

const displayCategories = computed(() =>
  newsStore.categories.filter((c) => c.name !== '更多')
)

const dailyRefs = computed(() => {
  const refs = daily.value?.refs || []
  const content = daily.value?.content || ''
  const cited = new Set([...content.matchAll(/\[(\d+)\]/g)].map((m) => Number(m[1])))
  const withNo = refs.map((ref, index) => ({ ...ref, no: index + 1 }))
  return (cited.size ? withNo.filter((ref) => cited.has(ref.no)) : withNo).slice(0, 4)
})

const isRead = (id) => readIds.value.includes(id)

const aiScore = (item) => {
  let score = 62
  score += Math.min(18, Math.floor((item.views || 0) / 500))
  const time = item.publishTime ? new Date(item.publishTime.replace(/-/g, '/')) : null
  if (time && !Number.isNaN(time.getTime())) {
    const hours = (Date.now() - time.getTime()) / 3600000
    score += hours < 24 ? 12 : hours < 72 ? 6 : 0
  }
  return Math.max(50, Math.min(96, score))
}

const timeOf = (item) => {
  if (!item.publishTime) return '--:--'
  const parts = item.publishTime.split(' ')
  return parts[1] ? parts[1].slice(0, 5) : item.publishTime
}

// 按发布日期分组
const groups = computed(() => {
  const list = readOnly.value
    ? newsStore.newsList.filter((item) => !isRead(item.id))
    : newsStore.newsList

  const buckets = new Map()
  for (const item of list) {
    const date = (item.publishTime || '').split(' ')[0] || '未知日期'
    if (!buckets.has(date)) buckets.set(date, [])
    buckets.get(date).push(item)
  }

  const weekdays = ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六']
  return [...buckets.entries()].map(([date, items]) => {
    const d = new Date(date.replace(/-/g, '/'))
    const label = Number.isNaN(d.getTime())
      ? date
      : `${d.getMonth() + 1}月${d.getDate()}日`
    return {
      date,
      label,
      weekday: Number.isNaN(d.getTime()) ? '' : weekdays[d.getDay()],
      items
    }
  })
})

const goDetail = (id) => router.push(`/news/detail/${id}`)

const toggleReadOnly = () => {
  readOnly.value = !readOnly.value
  readIds.value = getReadIds()
  if (readOnly.value && !groups.value.length) {
    showToast('当前分类没有未读新闻')
  }
}

const loadDaily = async () => {
  try {
    const response = await fetch(aiConfig.daily)
    const result = await response.json()
    if (result.code === 200) daily.value = result.data
  } catch (error) {
    console.error('今日要闻加载失败:', error)
  }
}

const pollRefresh = async () => {
  for (let i = 0; i < 40; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 1000))
    const response = await fetch(`${apiConfig.baseURL}/api/news/refresh/status`)
    const result = await response.json()
    const state = result.data || {}
    if (state.status === 'done') return state
    if (state.status === 'error') throw new Error(state.message || '抓取失败')
  }
  throw new Error('更新超时，请稍后再试')
}

const onRefresh = async () => {
  if (refreshingLive.value) return
  refreshingLive.value = true
  try {
    const response = await fetch(`${apiConfig.baseURL}/api/news/refresh`, { method: 'POST' })
    const result = await response.json()
    if (result.code === 429) {
      showToast(result.message || '刚刚更新过，请稍后再试')
    } else if (result.code === 409) {
      showToast('正在更新中，请稍候')
    } else {
      const state = await pollRefresh()
      showToast(state.added > 0 ? `已更新，新增 ${state.added} 条` : '暂无新新闻，稍后再试')
    }
  } catch (error) {
    showToast(error.message || '更新失败，请检查网络')
  } finally {
    refreshingLive.value = false
    await Promise.all([newsStore.getNewsList(true), loadDaily()])
  }
}

const switchCategory = (category) => {
  if (category.id === activeCategory.value) return
  activeCategory.value = category.id
  newsStore.changeCategory(category.id)
}

const onLoad = () => {
  if (newsStore.loading || newsStore.finished) return
  newsStore.getNewsList()
}

const doSearch = async () => {
  const q = keyword.value.trim()
  if (!q) return
  activeKeyword.value = q
  searchMode.value = true
  searching.value = true
  searchResults.value = []
  searchModeText.value = ''
  try {
    const response = await fetch(
      `${apiConfig.baseURL}/api/news/search?q=${encodeURIComponent(q)}&limit=20`
    )
    const result = await response.json()
    if (result.code === 200) {
      searchResults.value = result.data.list || []
      searchModeText.value = (
        { hybrid: '（标题+语义）', title: '（标题匹配）', semantic: '（语义匹配）', keyword: '（正文匹配）' }[
          result.data.mode
        ] || ''
      )
    }
  } catch (error) {
    console.error('搜索失败:', error)
  } finally {
    searching.value = false
  }
}

const clearSearch = () => {
  searchMode.value = false
  keyword.value = ''
  activeKeyword.value = ''
  searchResults.value = []
}

const loadUpdatedAt = async () => {
  try {
    const response = await fetch(`${apiConfig.baseURL}/api/news/updated-at`)
    const result = await response.json()
    if (result.code === 200) updatedAt.value = result.data.updatedAt || ''
  } catch (error) {
    console.error('更新时间获取失败:', error)
  }
}

const selectFromQuery = () => {
  const target = Number(route.query.categoryId)
  if (!target) return false
  const matched = displayCategories.value.find((c) => c.id === target)
  if (!matched) return false
  activeCategory.value = matched.id
  newsStore.currentCategory = matched.id
  newsStore.newsList = []
  newsStore.finished = false
  newsStore.getNewsList(true)
  return true
}

onMounted(async () => {
  await newsStore.getCategories()
  const list = displayCategories.value

  // 优先用 URL 里的分类；否则沿用上次选中的分类（可能来自「全部新闻」页）
  if (!selectFromQuery() && list.length) {
    const current = list.find((c) => c.id === newsStore.currentCategory) || list[0]
    activeCategory.value = current.id
    newsStore.currentCategory = current.id
    newsStore.newsList = []
    newsStore.finished = false
    await newsStore.getNewsList(true)
  }

  loadDaily()
  loadUpdatedAt()
  readIds.value = getReadIds()
})

// 从「全部新闻」页点分类进来时，切到对应分类
watch(
  () => route.query.categoryId,
  () => {
    if (route.path === '/home') selectFromQuery()
  }
)
</script>

<style scoped>
.hero-title {
  font-size: 30px;
  font-weight: 700;
  letter-spacing: 0.5px;
  margin: 0 0 18px;
  color: var(--text);
}

.filter-row {
  display: flex;
  align-items: center;
  gap: 18px;
  margin-bottom: 20px;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  flex: 1;
}

.chip {
  padding: 7px 16px;
  border-radius: 10px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-dim);
  font-size: 15px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.chip:hover {
  color: var(--text);
}

.chip.active {
  background: #1c1e24;
  color: #fff;
  font-weight: 600;
}

[data-theme='light'] .chip.active {
  background: #e8ebf0;
  color: #111;
}

.search-wrap {
  position: relative;
  width: 260px;
  flex-shrink: 0;
}

.search-input {
  width: 100%;
  padding: 9px 34px 9px 16px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--bg-input);
  color: var(--text);
  font-size: 14px;
  outline: none;
}

.search-input:focus {
  border-color: var(--brand);
}

.search-input::placeholder {
  color: var(--text-faint);
}

.search-key {
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  width: 20px;
  height: 20px;
  border-radius: 6px;
  border: 1px solid var(--border);
  color: var(--text-faint);
  font-size: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 热点 / 今日要闻 */
.hot-panel {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 18px 22px;
  margin-bottom: 28px;
}

.hot-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.hot-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #ff6b4a;
  box-shadow: 0 0 10px rgba(255, 107, 74, 0.6);
}

.hot-name {
  font-size: 16px;
  font-weight: 600;
  color: var(--text);
}

.hot-date {
  color: var(--text-faint);
  font-size: 13px;
}

.hot-body {
  white-space: pre-wrap;
  color: var(--text-dim);
  font-size: 15px;
  line-height: 1.9;
  border-top: 1px solid var(--border-soft);
  padding-top: 12px;
}

.hot-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
}

.hot-ref {
  color: var(--brand);
  font-size: 13px;
  cursor: pointer;
  max-width: 46%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.link-more {
  margin-left: auto;
  background: none;
  border: none;
  color: var(--text-dim);
  font-size: 13px;
  cursor: pointer;
}

.link-more:hover {
  color: var(--brand);
}

/* 日期分组 */
.day-block {
  margin-bottom: 26px;
}

.day-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 12px;
}

.day-title {
  font-size: 22px;
  font-weight: 700;
  margin: 0;
  color: var(--text);
}

.day-sub {
  color: var(--text-faint);
  font-size: 13px;
}

.ghost-btn {
  padding: 6px 14px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-dim);
  font-size: 13px;
  cursor: pointer;
}

.ghost-btn.on {
  border-color: var(--brand);
  color: var(--brand);
}

/* 新闻行 */
.feed-row {
  display: flex;
  gap: 14px;
  cursor: pointer;
}

.time-col {
  width: 52px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 16px;
  color: var(--text-faint);
  font-size: 12px;
}

.time-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--brand);
  box-shadow: 0 0 8px rgba(46, 230, 200, 0.6);
}

.time-dot.read {
  background: var(--border);
  box-shadow: none;
}

.feed-card {
  flex: 1;
  min-width: 0;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px 18px 16px;
  margin-bottom: 12px;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.feed-card:hover {
  border-color: #2b3040;
  background: var(--bg-card-hover);
}

.feed-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-dim);
}

.spacer {
  flex: 1;
}

.badge-tag {
  padding: 1px 7px;
  border-radius: 5px;
  background: rgba(212, 167, 106, 0.14);
  color: #d4a76a;
  font-size: 11px;
}

.badge-score {
  padding: 1px 9px;
  border-radius: 6px;
  border: 1px solid rgba(46, 230, 200, 0.35);
  color: var(--brand);
  font-size: 11px;
}

.feed-title {
  margin: 8px 0 8px;
  font-size: 19px;
  font-weight: 650;
  line-height: 1.5;
  color: var(--text);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.feed-desc {
  margin: 0;
  color: var(--text-dim);
  font-size: 15px;
  line-height: 1.8;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.reason {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--border-soft);
  color: var(--text-faint);
  font-size: 13px;
  line-height: 1.7;
}

.reason-label {
  color: var(--text-dim);
}

.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--text-dim);
  font-size: 14px;
  margin-bottom: 12px;
}

.list-foot {
  display: flex;
  justify-content: center;
  padding: 10px 0 30px;
}

.foot-text {
  color: var(--text-faint);
  font-size: 12px;
}

@media (max-width: 900px) {
  .hero-title {
    font-size: 24px;
  }

  .filter-row {
    flex-wrap: wrap;
    gap: 10px;
  }

  .search-wrap {
    width: 100%;
  }

  .time-col {
    display: none;
  }

  .feed-title {
    font-size: 16px;
  }

  .feed-desc {
    font-size: 14px;
  }

  .hot-panel {
    padding: 14px 16px;
  }
}
.hero-sub {
  margin: -12px 0 18px;
  color: var(--text-faint);
  font-size: 13px;
}

.refresh-btn {
  flex-shrink: 0;
}

.refresh-btn:disabled {
  opacity: 0.5;
  cursor: default;
}
</style>