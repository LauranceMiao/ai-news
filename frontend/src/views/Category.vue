<template>
  <div class="page">
    <h1 class="hero-title">全部新闻</h1>
    <p class="hero-sub">按分类浏览，切换分类不离开本页</p>

    <div class="chips">
      <button
        v-for="category in displayCategories"
        :key="category.id"
        class="chip"
        :class="{ active: category.id === selected }"
        @click="switchCategory(category.id)"
      >
        {{ category.name }}
      </button>
    </div>

    <div class="news-list">
      <article
        v-for="item in newsStore.newsList"
        :key="item.id"
        class="news-card"
        @click="goDetail(item.id)"
      >
        <div class="news-main">
          <div class="meta">
            <span class="tag" v-if="item.source">{{ item.source }}</span>
            <span>{{ item.publishTime }}</span>
            <span>{{ item.views || 0 }} 阅读</span>
          </div>
          <h3 class="news-title">{{ item.title }}</h3>
          <p class="news-desc">{{ item.description }}</p>
        </div>
        <img
          v-if="item.image"
          class="news-thumb"
          :src="item.image"
          referrerpolicy="no-referrer"
          loading="lazy"
          @error="hideImage"
        />
      </article>
    </div>

    <van-empty
      v-if="!newsStore.loading && !newsStore.newsList.length"
      description="该分类暂无新闻"
    />

    <div class="list-foot">
      <button v-if="newsStore.loading" class="ghost-btn" disabled>加载中…</button>
      <button v-else-if="!newsStore.finished" class="ghost-btn" @click="loadMore">加载更多</button>
      <span v-else class="foot-text">已经到底了</span>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useNewsStore } from '../store/modules/news'

const newsStore = useNewsStore()
const router = useRouter()

const selected = ref(null)

const displayCategories = computed(() =>
  newsStore.categories.filter((category) => category.name !== '更多')
)

const goDetail = (id) => router.push(`/news/detail/${id}`)
const hideImage = (event) => {
  event.target.style.display = 'none'
}

const switchCategory = async (id) => {
  if (id === selected.value) return
  selected.value = id
  newsStore.currentCategory = id
  newsStore.newsList = []
  newsStore.finished = false
  await newsStore.getNewsList(true)
}

const loadMore = () => {
  if (newsStore.loading || newsStore.finished) return
  newsStore.getNewsList()
}

onMounted(async () => {
  if (!newsStore.categories.length) {
    await newsStore.getCategories()
  }
  const list = displayCategories.value
  if (!list.length) return

  // 首次进入沿用首页选中的分类，没有就选第一个
  const current = list.find((c) => c.id === newsStore.currentCategory)
  selected.value = current ? current.id : list[0].id
  newsStore.currentCategory = selected.value
  newsStore.newsList = []
  newsStore.finished = false
  await newsStore.getNewsList(true)
})
</script>

<style scoped>
.hero-title {
  font-size: 30px;
  font-weight: 700;
  margin: 0 0 6px;
  color: var(--text);
}

.hero-sub {
  color: var(--text-faint);
  font-size: 13px;
  margin: 0 0 18px;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 18px;
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

.news-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.news-card {
  display: flex;
  gap: 16px;
  padding: 16px 18px;
  border-radius: 14px;
  border: 1px solid var(--border);
  background: var(--bg-card);
  cursor: pointer;
  transition: all 0.15s ease;
}

.news-card:hover {
  border-color: var(--brand);
  background: var(--bg-card-hover);
}

.news-main {
  flex: 1;
  min-width: 0;
}

.meta {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--text-faint);
  font-size: 12px;
}

.tag {
  padding: 1px 8px;
  border-radius: 6px;
  background: rgba(46, 230, 200, 0.12);
  color: var(--brand);
  font-size: 11px;
}

.news-title {
  margin: 8px 0 6px;
  font-size: 16px;
  font-weight: 600;
  line-height: 1.5;
  color: var(--text);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.news-desc {
  margin: 0;
  color: var(--text-dim);
  font-size: 13px;
  line-height: 1.7;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.news-thumb {
  width: 132px;
  height: 92px;
  border-radius: 10px;
  object-fit: cover;
  flex-shrink: 0;
  background: var(--bg-input);
}

.ghost-btn {
  padding: 8px 22px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-dim);
  font-size: 13px;
  cursor: pointer;
}

.ghost-btn:hover {
  color: var(--text);
  border-color: var(--brand);
}

.list-foot {
  display: flex;
  justify-content: center;
  padding: 22px 0 10px;
}

.foot-text {
  color: var(--text-faint);
  font-size: 12px;
}

@media (max-width: 900px) {
  .hero-title {
    font-size: 24px;
  }

  .news-thumb {
    width: 96px;
    height: 72px;
  }
}
</style>
