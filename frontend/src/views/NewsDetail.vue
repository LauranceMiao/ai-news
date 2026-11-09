<template>
  <div class="news-detail">
    <van-nav-bar
      title="新闻详情"
      left-text="返回"
      left-arrow
      @click-left="onClickLeft"
      fixed
    />
    
    <div class="detail-content" v-if="newsStore.newsDetail.id">
      <!-- 桌面端没有顶部导航栏，这里补一个返回 -->
      <div class="detail-top">
        <button class="back-btn" @click="onClickLeft">← 返回</button>
        <span class="crumb">新闻详情</span>
      </div>

      <div class="title-container">
        <h1 class="title">{{ newsStore.newsDetail.title }}</h1>
        <van-button 
          class="favorite-btn" 
          :icon="isFavorite ? 'star' : 'star-o'" 
          :class="{ 'is-favorite': isFavorite }"
          @click="toggleFavorite"
        />
      </div>
      
      <div class="info">
        <span>{{ newsStore.newsDetail.author }}</span>
        <span>{{ newsStore.newsDetail.publishTime }}</span>
        <span>{{ newsStore.newsDetail.views }} 阅读</span>
      </div>

      <!-- 热搜话题：站内没有正文，引导去看原文 -->
      <div class="hot-card" v-if="isHot">
        <div class="hot-card-head">
          <span class="hot-badge">热搜</span>
          <span class="hot-label">该话题来自百度热搜，站内暂无正文</span>
        </div>
        <div class="hot-meta">
          <span>热度 {{ newsStore.newsDetail.hotScore }}</span>
          <span v-if="newsStore.newsDetail.sourceUrl">原文含完整报道</span>
        </div>
        <van-button
          type="primary"
          size="small"
          block
          v-if="newsStore.newsDetail.sourceUrl"
          @click="openSource"
        >
          去百度查看完整报道
        </van-button>
        <div class="hot-tip">下面是站内与这个话题相关的报道，可以直接读</div>
      </div>

      <!-- AI 摘要（热搜话题没有正文，不展示） -->
      <div class="ai-card" v-if="!isHot">
        <div class="ai-card-header">
          <span class="ai-badge">AI</span>
          <span class="ai-card-title">智能摘要</span>
          <van-button
            size="mini"
            plain
            type="primary"
            :loading="summaryLoading"
            loading-text="生成中"
            @click="loadSummary(!!summary)"
          >
            {{ summary ? '换一版' : '生成摘要' }}
          </van-button>
        </div>
        <div v-if="summaryLoading && !summary" class="ai-skeleton">正在阅读全文并提炼要点...</div>
        <div v-else-if="summary" class="ai-body">
          <p class="ai-summary">{{ summary }}</p>
          <ul v-if="points.length" class="ai-points">
            <li v-for="(point, i) in points" :key="i">{{ point }}</li>
          </ul>
          <div class="ai-meta" v-if="uiConfig.showCost && summaryUsage">
            {{ summaryUsage.model }} · {{ summaryUsage.totalTokens }} tokens · ¥{{ summaryUsage.cost.toFixed(4) }}
            <span v-if="summaryCached"> · 来自缓存</span>
          </div>
        </div>
        <div v-else-if="summaryError" class="ai-error">{{ summaryError }}</div>
      </div>
      
      <div class="cover" v-if="newsStore.newsDetail.image">
        <img
          :src="newsStore.newsDetail.image"
          :alt="newsStore.newsDetail.title"
          referrerpolicy="no-referrer"
          @error="$event.target.parentElement.style.display = 'none'"
        >
      </div>
      
      <div class="content">
        <p v-for="(paragraph, index) in contentParagraphs" :key="index">
          {{ paragraph }}
        </p>
      </div>
      
      <div class="related-news" v-if="newsStore.newsDetail.relatedNews?.length">
        <h3>相关推荐</h3>
        <div class="related-list">
          <div 
            class="related-item" 
            v-for="item in newsStore.newsDetail.relatedNews" 
            :key="item.id"
            @click="goToRelatedNews(item.id)"
          >
            <div class="related-image" v-if="item.image">
              <img
                :src="item.image"
                :alt="item.title"
                loading="lazy"
                referrerpolicy="no-referrer"
                @error="$event.target.parentElement.style.display = 'none'"
              >
            </div>
            <div class="related-title" :class="{ 'no-image': !item.image }">{{ item.title }}</div>
          </div>
        </div>
      </div>
    </div>
    
    <van-empty v-else :description="notFound ? '这篇新闻不存在或已下线' : '加载中...'">
      <van-button v-if="notFound" type="primary" size="small" @click="onClickLeft">返回</van-button>
    </van-empty>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useNewsStore } from '../store/modules/news'
import { useHistoryStore } from '../store/modules/history'
import { useFavoriteStore } from '../store/modules/favorite'
import { useUserStore } from '../store/user'
import { showToast } from 'vant'
import { aiConfig, uiConfig } from '../config/api'
import { markRead } from '../utils/readState'

const route = useRoute()
const router = useRouter()
const newsStore = useNewsStore()
const historyStore = useHistoryStore()
const favoriteStore = useFavoriteStore()
const userStore = useUserStore()

// 获取路由参数中的新闻ID
const newsId = computed(() => Number(route.params.id))

// 是否为热搜话题（站内没有正文）
const isHot = computed(() => newsStore.newsDetail.source === 'baidu_hot')

const notFound = ref(false)

// 去百度看原文
const openSource = () => {
  const url = newsStore.newsDetail.sourceUrl
  if (url) window.open(url, '_blank')
}

// 将内容拆分为段落（热搜条目把原始链接那几行藏起来，用按钮代替）
const contentParagraphs = computed(() => {
  if (!newsStore.newsDetail.content) return []
  return newsStore.newsDetail.content
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith('原文链接') && !line.startsWith('说明：') && !/^https?:\/\//.test(line))
})

// ---------- AI 摘要 ----------
const summary = ref('')
const points = ref([])
const summaryLoading = ref(false)
const summaryError = ref('')
const summaryUsage = ref(null)
const summaryCached = ref(false)

const loadSummary = async (force = false) => {
  if (summaryLoading.value) return
  summaryLoading.value = true
  summaryError.value = ''
  try {
    const response = await fetch(aiConfig.summary, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ newsId: newsId.value, force }),
    })
    const result = await response.json().catch(() => ({}))
    if (!response.ok) {
      throw new Error(result.detail || `生成失败（${response.status}）`)
    }
    const data = result.data || {}
    summary.value = data.summary || ''
    points.value = data.points || []
    summaryUsage.value = data.usage && data.usage.totalTokens ? data.usage : null
    summaryCached.value = !!data.cached
  } catch (error) {
    console.error('AI 摘要失败:', error)
    summaryError.value = `摘要生成失败：${error.message}`
  } finally {
    summaryLoading.value = false
  }
}

// 返回上一页
const onClickLeft = () => {
  router.back()
}

// 跳转到相关新闻
const goToRelatedNews = (id) => {
  router.push(`/news/detail/${id}`)
}

// 判断当前新闻是否已收藏
const isFavorite = computed(() => {
  return favoriteStore.isFavorite(newsId.value)
})

// 切换收藏状态
const toggleFavorite = async () => {
  // 判断用户是否已登录
  if (!userStore.getLoginStatus) {
    // 未登录则跳转到登录页
    showToast({
      message: '请先登录后再收藏',
      position: 'bottom',
    })
    router.push('/login')
    return
  }
  
  // 已登录则调用API切换收藏状态
  const status = await favoriteStore.toggleFavorite(newsStore.newsDetail)
  
  if (status === true) {
    showToast({
      message: '已添加到收藏',
      position: 'bottom',
    })
  } else if (status === false) {
    showToast({
      message: '已取消收藏',
      position: 'bottom',
    })
  } else {
    // status为null表示操作失败
    showToast({
      message: '操作失败，请稍后重试',
      position: 'bottom',
    })
  }
}

// 加载某篇新闻（详情页复用同一个组件，切换 id 时要能重新加载）
const loadDetail = async (id) => {
  summary.value = ''
  points.value = []
  summaryError.value = ''
  summaryUsage.value = null
  notFound.value = false

  await newsStore.getNewsDetail(id)
  notFound.value = !newsStore.newsDetail.id
  if (notFound.value) return
  markRead(newsStore.newsDetail.id)

  // 添加到浏览历史：登录了就写服务端，没登录就存本地
  if (userStore.getLoginStatus) {
    try {
      const result = await historyStore.addHistoryApi(newsStore.newsDetail.id);
      if (!result.success) {
        historyStore.addHistory(newsStore.newsDetail);
      }
    } catch (error) {
      console.error('记录浏览历史API失败:', error);
      historyStore.addHistory(newsStore.newsDetail);
    }
  } else {
    historyStore.addHistory(newsStore.newsDetail);
  }

  // 加载收藏数据
  favoriteStore.loadFavorites()

  // 检查文章收藏状态
  if (userStore.getLoginStatus) {
    const result = await favoriteStore.checkFavoriteStatusApi(newsStore.newsDetail.id)
    if (result.success && !result.isLocal) {
      if (result.isFavorite && !favoriteStore.isFavorite(newsStore.newsDetail.id)) {
        favoriteStore.addFavorite(newsStore.newsDetail)
      } else if (!result.isFavorite && favoriteStore.isFavorite(newsStore.newsDetail.id)) {
        favoriteStore.removeFavorite(newsStore.newsDetail.id)
      }
    }
  }
}

// 组件挂载
onMounted(() => loadDetail(newsId.value))

// 同一个组件内切换新闻（点相关推荐）：复用组件不会触发 onMounted，必须监听路由参数
watch(newsId, (id) => {
  if (!id || Number.isNaN(id)) return
  loadDetail(id)
  window.scrollTo({ top: 0, behavior: 'auto' })
})
</script>

<style scoped>
.news-detail {
  padding-top: 46px;
  background-color: #fff;
  min-height: 100vh;
}

.detail-content {
  padding: 16px;
}

.title-container {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 12px;
}

.title {
  font-size: 22px;
  font-weight: bold;
  line-height: 1.4;
  margin: 0;
  flex: 1;
}

.favorite-btn {
  flex-shrink: 0;
  margin-left: 10px;
  padding: 0;
  width: 36px;
  height: 36px;
  border-radius: 50%;
}

.favorite-btn.is-favorite {
  color: #ff9500;
}

.info {
  display: flex;
  font-size: 12px;
  color: #999;
  margin-bottom: 16px;
}

.info span {
  margin-right: 12px;
}

.cover {
  margin-bottom: 16px;
}

/* 热搜话题卡片 */
.hot-card {
  background: #fff8f5;
  border: 1px solid #ffe0d3;
  border-radius: 10px;
  padding: 12px;
  margin-bottom: 16px;
}

.hot-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.hot-badge {
  background: #ff5722;
  color: #fff;
  font-size: 11px;
  font-weight: bold;
  padding: 1px 6px;
  border-radius: 4px;
}

.hot-label {
  font-size: 13px;
  color: #8a5a45;
}

.hot-meta {
  display: flex;
  gap: 14px;
  font-size: 12px;
  color: #b08a78;
  margin-bottom: 10px;
}

.hot-tip {
  margin-top: 10px;
  font-size: 12px;
  color: #999;
}

/* AI 摘要卡片 */
.ai-card {  background: linear-gradient(135deg, #eef4ff 0%, #f7fbff 100%);
  border: 1px solid #dce8ff;
  border-radius: 10px;
  padding: 12px;
  margin-bottom: 16px;
}

.ai-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.ai-badge {
  background: #1989fa;
  color: #fff;
  font-size: 11px;
  font-weight: bold;
  padding: 1px 6px;
  border-radius: 4px;
  letter-spacing: 1px;
}

.ai-card-title {
  font-size: 14px;
  font-weight: 600;
  color: #1f2d3d;
  flex: 1;
}

.ai-summary {
  margin: 0 0 8px;
  font-size: 14px;
  line-height: 1.7;
  color: #333;
  text-align: justify;
}

.ai-points {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  color: #555;
  line-height: 1.7;
}

.ai-skeleton {
  font-size: 13px;
  color: #8a94a6;
  padding: 6px 0;
}

.ai-error {
  font-size: 13px;
  color: #e64340;
}

.ai-meta {
  margin-top: 8px;
  font-size: 11px;
  color: #a0a8b8;
}

.cover img {
  width: 100%;
  border-radius: 4px;
}

.content {
  font-size: 16px;
  line-height: 1.8;
  color: #333;
}

.content p {
  margin-bottom: 16px;
  text-align: justify;
}

.related-news {
  margin-top: 24px;
  padding-top: 16px;
  border-top: 8px solid #f5f5f5;
}

.related-news h3 {
  font-size: 18px;
  margin: 0 0 16px;
}

.related-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.related-item {
  display: flex;
  align-items: center;
}

.related-image {
  width: 80px;
  height: 60px;
  margin-right: 12px;
  flex-shrink: 0;
}

.related-image img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: 4px;
}

.related-title {
  font-size: 14px;
  line-height: 1.4;
  flex: 1;
}

.related-title.no-image {
  margin-left: 0;
}
/* ---- 新主题适配 ---- */
.news-detail {
  background: var(--bg) !important;
  padding-top: 0 !important;
}
.title { color: var(--text); }
.info, .info span { color: var(--text-faint); }
.content, .content p { color: var(--text); }
.related-news { border-top: 1px solid var(--border); }
.related-news h3 { color: var(--text); }
.related-title { color: var(--text-dim); }
.ai-card {
  background: var(--bg-card) !important;
  border-color: var(--border) !important;
}
.ai-card-title { color: var(--text); }
.ai-summary { color: var(--text); }
.ai-points { color: var(--text-dim); }
/* 桌面端返回条 */
.detail-top {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}

.back-btn {
  padding: 6px 14px;
  border-radius: 9px;
  border: 1px solid var(--border);
  background: var(--bg-card);
  color: var(--text-dim);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.back-btn:hover {
  color: var(--text);
  border-color: var(--brand);
}

.crumb {
  color: var(--text-faint);
  font-size: 12px;
}

@media (min-width: 901px) {
  .cover img {
    max-height: 460px;
    width: 100%;
    object-fit: cover;
    border-radius: 12px;
  }
}

@media (max-width: 900px) {
  .detail-top {
    display: none;
  }
}
</style>