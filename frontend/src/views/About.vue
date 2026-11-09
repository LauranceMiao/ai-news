<template>
  <div class="page about">
    <!-- 顶部：3D 立方体 + 标题 -->
    <section class="hero">
      <div class="scene">
        <div class="cube">
          <span class="face front">AI</span>
          <span class="face back">RAG</span>
          <span class="face right">SSE</span>
          <span class="face left">JWT</span>
          <span class="face top">Agent</span>
          <span class="face bottom">SQL</span>
        </div>
        <div class="glow"></div>
      </div>

      <div class="hero-text">
        <h1 class="hero-title">
          AI 新闻聚合<span class="accent">与</span>问答系统
        </h1>
        <p class="hero-sub">
          抓取实时新闻 → 本地向量化 → 检索增强问答，一个能溯源、可多步检索的新闻工作台。
        </p>
        <div class="stats">
          <div class="stat">
            <b>378</b>
            <span>实时新闻</span>
          </div>
          <div class="stat">
            <b>2649</b>
            <span>向量切片</span>
          </div>
          <div class="stat">
            <b>4</b>
            <span>Agent 工具</span>
          </div>
          <div class="stat">
            <b>1s</b>
            <span>首字响应</span>
          </div>
        </div>
      </div>
    </section>

    <!-- 功能卡片 -->
    <section class="feature-grid">
      <article
        v-for="item in features"
        :key="item.title"
        class="feature-card"
        @mousemove="tilt"
        @mouseleave="resetTilt"
      >
        <div class="feature-icon">{{ item.icon }}</div>
        <h3>{{ item.title }}</h3>
        <p>{{ item.desc }}</p>
      </article>
    </section>


    <p class="footnote">
      个人学习项目 · 新闻内容来自公开 RSS 源，AI 生成内容仅供参考，请以原文为准。
    </p>
  </div>
</template>

<script setup>
const features = [
  {
    icon: '⛁',
    title: '实时聚合',
    desc: '11 个 RSS 源手动刷新入库，7 天外的旧闻自动丢弃，标题去重。'
  },
  {
    icon: '⌘',
    title: 'RAG 问答',
    desc: '本地 bge 向量化，余弦召回 + 阈值过滤，答案带 [1][2] 引用可跳转。'
  },
  {
    icon: '✦',
    title: '多步 Agent',
    desc: '复杂问题自动调用检索/详情/摘要工具，最多 3 轮，前端展示调用轨迹。'
  },
  {
    icon: '▤',
    title: 'AI 摘要与要闻',
    desc: '单篇摘要 100 字 + 3 条要点，每日要闻自动聚合，结果落库缓存。'
  },
  {
    icon: '⌕',
    title: '混合搜索',
    desc: '标题关键词优先、语义召回补充、正文兜底，短词不会被语义带偏。'
  },
  {
    icon: '◐',
    title: '多端适配',
    desc: '桌面侧栏与移动端 Tab 自适应，深浅两套主题一键切换。'
  }
]

// 鼠标移动时的 3D 倾斜
const tilt = (event) => {
  const el = event.currentTarget
  const rect = el.getBoundingClientRect()
  const x = (event.clientX - rect.left) / rect.width - 0.5
  const y = (event.clientY - rect.top) / rect.height - 0.5
  el.style.transform = `perspective(700px) rotateX(${(-y * 6).toFixed(2)}deg) rotateY(${(x * 8).toFixed(2)}deg) translateY(-2px)`
}

const resetTilt = (event) => {
  event.currentTarget.style.transform = ''
}
</script>

<style scoped>
.about {
  position: relative;
}

/* ---------- Hero ---------- */
.hero {
  display: flex;
  align-items: center;
  gap: 42px;
  padding: 26px 30px 30px;
  border-radius: 18px;
  border: 1px solid var(--border);
  background:
    radial-gradient(120% 140% at 12% 0%, rgba(46, 230, 200, 0.1), transparent 55%),
    linear-gradient(180deg, var(--bg-card), var(--bg));
  overflow: hidden;
  margin-bottom: 22px;
}

.hero::after {
  content: '';
  position: absolute;
  inset: 0;
  background-image: linear-gradient(rgba(255, 255, 255, 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.03) 1px, transparent 1px);
  background-size: 36px 36px;
  mask-image: radial-gradient(80% 80% at 70% 20%, #000, transparent);
  pointer-events: none;
}

[data-theme='light'] .hero::after {
  background-image: linear-gradient(rgba(0, 0, 0, 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0, 0, 0, 0.035) 1px, transparent 1px);
}

/* 3D 立方体 */
.scene {
  position: relative;
  width: 150px;
  height: 150px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  perspective: 620px;
}

.cube {
  position: relative;
  width: 84px;
  height: 84px;
  transform-style: preserve-3d;
  animation: spin 16s linear infinite;
}

.face {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 1px;
  color: var(--brand);
  background: rgba(46, 230, 200, 0.06);
  border: 1px solid rgba(46, 230, 200, 0.45);
  box-shadow: inset 0 0 22px rgba(46, 230, 200, 0.18);
  border-radius: 8px;
  backdrop-filter: blur(2px);
}

.front { transform: translateZ(42px); }
.back { transform: rotateY(180deg) translateZ(42px); }
.right { transform: rotateY(90deg) translateZ(42px); }
.left { transform: rotateY(-90deg) translateZ(42px); }
.top { transform: rotateX(90deg) translateZ(42px); }
.bottom { transform: rotateX(-90deg) translateZ(42px); }

@keyframes spin {
  from { transform: rotateX(-18deg) rotateY(0deg); }
  to { transform: rotateX(-18deg) rotateY(360deg); }
}

.glow {
  position: absolute;
  width: 150px;
  height: 150px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(46, 230, 200, 0.25), transparent 65%);
  filter: blur(12px);
  z-index: -1;
}

.hero-text {
  flex: 1;
  min-width: 0;
}

.hero-title {
  font-size: 30px;
  font-weight: 700;
  margin: 0 0 10px;
  color: var(--text);
  letter-spacing: 0.5px;
}

.accent {
  color: var(--brand);
}

.hero-sub {
  margin: 0 0 18px;
  color: var(--text-dim);
  font-size: 15px;
  line-height: 1.8;
  max-width: 640px;
}

.stats {
  display: flex;
  flex-wrap: wrap;
  gap: 26px;
}

.stat b {
  display: block;
  font-size: 20px;
  color: var(--text);
  letter-spacing: 0.5px;
}

.stat span {
  color: var(--text-faint);
  font-size: 12px;
}

/* ---------- 功能卡片 ---------- */
.feature-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 22px;
}

.feature-card {
  position: relative;
  padding: 20px;
  border-radius: 14px;
  border: 1px solid var(--border);
  background: var(--bg-card);
  transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
  transform-style: preserve-3d;
  will-change: transform;
}

.feature-card:hover {
  border-color: rgba(46, 230, 200, 0.45);
  box-shadow: 0 12px 30px rgba(0, 0, 0, 0.25), 0 0 0 1px rgba(46, 230, 200, 0.12);
}

.feature-icon {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 17px;
  color: var(--brand);
  background: rgba(46, 230, 200, 0.1);
  border: 1px solid rgba(46, 230, 200, 0.25);
  margin-bottom: 12px;
}

.feature-card h3 {
  margin: 0 0 6px;
  font-size: 16px;
  font-weight: 650;
  color: var(--text);
}

.feature-card p {
  margin: 0;
  color: var(--text-dim);
  font-size: 13px;
  line-height: 1.75;
}

.footnote {
  margin: 18px 0 0;
  color: var(--text-faint);
  font-size: 12px;
}

@media (max-width: 900px) {
  .hero {
    flex-direction: column;
    align-items: flex-start;
    gap: 16px;
    padding: 20px;
  }

  .scene {
    width: 110px;
    height: 110px;
  }

  .cube {
    width: 66px;
    height: 66px;
  }

  .front, .back, .right, .left, .top, .bottom {
    transform-origin: center;
  }

  .front { transform: translateZ(33px); }
  .back { transform: rotateY(180deg) translateZ(33px); }
  .right { transform: rotateY(90deg) translateZ(33px); }
  .left { transform: rotateY(-90deg) translateZ(33px); }
  .top { transform: rotateX(90deg) translateZ(33px); }
  .bottom { transform: rotateX(-90deg) translateZ(33px); }

  .hero-title {
    font-size: 22px;
  }

  .feature-grid {
    grid-template-columns: 1fr;
  }
}
</style>
