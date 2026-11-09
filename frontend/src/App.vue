<template>
  <div class="app-shell">
    <div v-if="drawerOpen" class="sidebar-mask" @click="drawerOpen = false"></div>

    <aside class="sidebar" :class="{ open: drawerOpen }">
      <div class="brand">
        <span class="brand-dot"></span>
        <span>AI 新闻</span>
      </div>

      <div class="side-group">内容</div>
      <nav class="side-nav">
        <router-link
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="side-link"
          @click="drawerOpen = false"
        >
          <span class="side-icon">{{ item.icon }}</span>
          <span>{{ item.label }}</span>
        </router-link>
      </nav>

      <div class="side-foot">
        <button class="theme-toggle" @click="theme.toggle()">
          <span>{{ theme.isDark ? '深色模式' : '浅色模式' }}</span>
          <span>{{ theme.isDark ? '🌙' : '☀️' }}</span>
        </button>
      </div>
    </aside>

    <div class="main-wrap">
      <header class="topbar">
        <button class="icon-btn" @click="drawerOpen = true">☰</button>
        <span class="topbar-title">{{ currentTitle }}</span>
        <button class="icon-btn" @click="theme.toggle()">
          {{ theme.isDark ? '🌙' : '☀️' }}
        </button>
      </header>

      <main class="main">
        <router-view v-slot="{ Component }">
          <component :is="Component" />
        </router-view>
      </main>
    </div>

    <nav class="mobile-tabbar">
      <router-link
        v-for="item in tabItems"
        :key="item.to"
        :to="item.to"
        class="tab-item"
        :class="{ active: isActive(item.to) }"
      >
        <span class="tab-icon">{{ item.icon }}</span>
        <span class="tab-label">{{ item.label }}</span>
      </router-link>
    </nav>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useThemeStore } from './store/theme'

const theme = useThemeStore()
theme.initTheme()

const route = useRoute()
const drawerOpen = ref(false)

const navItems = [
  { to: '/home', label: '精选', icon: '✦' },
  { to: '/category', label: '全部新闻', icon: '▤' },
  { to: '/aichat', label: 'AI 问答', icon: '✳' },
  { to: '/favorite', label: '我的收藏', icon: '☆' },
  { to: '/history', label: '浏览历史', icon: '◷' },
  { to: '/my', label: '我的', icon: '◍' },
  { to: '/settings', label: '设置', icon: '⚙' },
  { to: '/about', label: '关于', icon: 'ℹ' }
]

const tabItems = [
  { to: '/home', label: '精选', icon: '✦' },
  { to: '/category', label: '分类', icon: '▤' },
  { to: '/aichat', label: 'AI 问答', icon: '✳' },
  { to: '/my', label: '我的', icon: '◍' }
]

const titles = {
  '/home': '精选',
  '/category': '全部新闻',
  '/aichat': 'AI 问答',
  '/favorite': '我的收藏',
  '/history': '浏览历史',
  '/settings': '设置',
  '/about': '关于',
  '/my': '我的'
}

const currentTitle = computed(() => {
  if (route.path.startsWith('/news/detail')) return '新闻详情'
  return titles[route.path] || 'AI 新闻'
})

const isActive = (to) => route.path === to
</script>

<style>
.mobile-tabbar {
  display: none;
}

@media (max-width: 900px) {
  .mobile-tabbar {
    display: flex;
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    height: 58px;
    background: var(--bg-sidebar);
    border-top: 1px solid var(--border);
    z-index: 40;
    padding-bottom: env(safe-area-inset-bottom);
  }

  .tab-item {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 2px;
    color: var(--text-faint);
    font-size: 11px;
  }

  .tab-item.active {
    color: var(--brand);
  }

  .tab-icon {
    font-size: 17px;
    line-height: 1;
  }
}
</style>
