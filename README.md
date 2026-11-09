# AI 新闻聚合与问答系统

基于 **Vue 3 + FastAPI + MySQL + 本地向量检索 + DeepSeek** 的新闻聚合与智能问答系统。
在原「头条新闻」项目的基础上，补齐了 **RAG 检索增强问答、新闻 AI 摘要、今日要闻、语义相关推荐、手动刷新采集（11 个 RSS 源）** 与 **JWT 鉴权**。

---

## 1. 功能特性

| 模块 | 说明 |
|---|---|
| 新闻浏览 | 分类 Tab、分页加载、下拉刷新、详情页（浏览量 +1、相关推荐） |
| 用户体系 | 注册 / 登录，**JWT** 鉴权（替换原数据库 token） |
| 收藏 / 历史 | 登录后收藏新闻、记录浏览历史 |
| **AI 摘要** | 详情页一键生成「100 字摘要 + 3 条要点」，结果入库缓存，二次打开不再消耗 token |
| **AI 问答（SSE）** | 基于 RAG 的流式回答，答案带 `[1][2]` 引用编号，前端展示参考新闻与相似度 |
| **Agent 工具循环** | 模型自主决定检索顺序与次数（4 个工具 + 结束工具），支持「任务模式」拆解多步任务，前端展示每一步轨迹 |
| **今日要闻** | 按天聚合新闻，用 pro 模型生成一段总览，首页卡片展示，按日期缓存 |
| **语义相关新闻** | 用向量检索替代「同分类随机」，推荐真正内容相近的新闻 |
| **手动刷新采集** | 点刷新才抓：中新网 6 个频道（头条/社会/国际/文化/体育/财经）+ 新浪 + IT之家 / 爱范儿 / Solidot / 少数派，入库即建索引，带保留策略 |
| **成本可视化** | 每次调用返回 token 用量与费用估算，区分 fast / pro 模型 |

## 2. 技术栈

- **前端**：Vue 3、Vite、Pinia、Vue Router、Vant 4、marked + DOMPurify
- **后端**：FastAPI、SQLAlchemy 2.x（async）、aiomysql、PyJWT、httpx
- **数据库**：MySQL 8.0
- **向量**：fastembed + `BAAI/bge-small-zh-v1.5`（ONNX，CPU 可跑，512 维，无需外部 embedding API）
- **大模型**：DeepSeek `deepseek-flash`（快）/ `deepseek-v4-pro`（强），OpenAI 兼容协议

## 3. 请求链路

```
前端 /api/ai/chat (POST)
   └─> 问题向量化 (bge-small-zh)
        └─> 余弦相似度召回 Top-K 新闻切片
             └─> 拼接 Prompt（带 [1][2] 编号）
                  └─> DeepSeek 流式生成（SSE 逐字返回）
                       └─> 落库会话 + 返回引用新闻 + token 成本
```

## 4. 目录结构

```
AI 新闻聚合与问答系统/
├── backend/
│   ├── config/          # settings(.env) / db_conf
│   ├── models/          # ORM：news / users / ai(chunk, summary, session…)
│   ├── schemas/         # Pydantic 请求模型
│   ├── crud/            # 数据库操作封装
│   ├── routers/         # news / users / favorites / history / ai / rss
│   ├── services/
│   │   ├── llm_client.py   # DeepSeek 客户端：路由 / 重试 / 成本
│   │   ├── embeddings.py   # 本地 bge 向量化
│   │   ├── rag.py          # 切分 / 索引 / 召回 / Prompt
│   │   ├── digest.py       # 今日要闻
│   │   ├── rss_fetcher.py  # RSS 采集
│   │   └── cache.py        # TTL + LRU 缓存
│   ├── scripts/         # build_index.py / fetch_rss.py
│   ├── sql/             # 建表脚本
│   ├── tests/           # pytest
│   ├── .env.example
│   └── requirements.txt
├── frontend/
│   └── src/views/       # Home(今日要闻) / NewsDetail(AI摘要) / AIChat(RAG问答)
└── README.md
```

## 5. 快速开始

### 5.1 准备数据库

```bash
# 新建库（如果还没有）
mysql -uroot -p -e "CREATE DATABASE news_ai CHARACTER SET utf8mb4;"

# 导入新闻数据（可选，用你原有的数据）
mysql -uroot -p news_ai < your_dump.sql

# 建 AI 相关表
mysql -uroot -p news_ai < backend/sql/ai_schema.sql
```

### 5.2 后端

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt

copy .env.example .env          # 填入 DEEPSEEK_API_KEY 和数据库密码
python -m uvicorn main:app --reload --port 8000
```

访问 <http://127.0.0.1:8000/docs> 查看接口文档。

### 5.3 建立向量索引（首次必须）

```bash
cd backend
python -m scripts.build_index            # 增量
python -m scripts.build_index --force    # 全量重建
python -m scripts.build_index --limit 50 # 先试跑 50 条
```

首次运行会下载 `bge-small-zh-v1.5` 模型（约 95MB）。国内网络建议 `.env` 里保留
`HF_ENDPOINT=https://hf-mirror.com`；如果仍很慢，可从 ModelScope 下载同名
`model_optimized.onnx` 放到 `backend/.cache/fastembed/models--Qdrant--bge-small-zh-v1.5/snapshots/<hash>/` 下。

### 5.4 前端

```bash
cd frontend
npm install
npm run dev
```

打开 <http://localhost:5173>。若后端地址不是 `127.0.0.1:8000`，改 `src/config/api.js`。

> 首屏默认展示库里已有的新闻。**首页下拉刷新**（或点右上角刷新图标）会触发一次手动采集：
> 抓百度热搜 + 6 个 RSS 源 → 去重入库 → 增量建索引，9 秒左右完成，之后列表顶部就是刚抓到的新新闻。

> 也可以直接双击根目录的 `start-backend.bat` 和 `start-frontend.bat` 启动。

## 6. 主要接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/news/categories` | 分类列表 |
| GET | `/api/news/list?categoryId=&page=&pageSize=` | 新闻分页 |
| GET | `/api/news/detail?id=` | 新闻详情 + 相关新闻 |
| POST | `/api/news/refresh?per_feed=&hot_limit=` | **手动采集**（立即返回，前端轮询进度） |
| GET | `/api/news/refresh/status` | 采集状态：idle / running / done / error |
| GET | `/api/news/updated-at` | 最近更新时间与实时新闻条数 |
| POST | `/api/user/register` / `/api/user/login` | 注册 / 登录（返回 JWT） |
| GET | `/api/user/profile` | 当前用户（需 `Authorization: Bearer <token>`） |
| POST | `/api/ai/summary` | 单篇摘要 `{newsId, force}` |
| POST | `/api/ai/chat` | RAG 问答，**SSE 流式** `{question, sessionId?, newsId?}` |
| GET | `/api/ai/daily?date=&categoryId=` | 今日要闻 |
| GET | `/api/ai/related?newsId=&limit=` | 语义相关新闻 |
| GET | `/api/ai/sessions` | 我的会话（需登录） |
| GET | `/api/ai/stats` | 索引规模 / 缓存命中率 |
| POST | `/api/rss/fetch?max=` | 手动抓一轮 RSS |
| POST | `/api/ai/reindex` | 手动建索引（演示用） |

### SSE 事件格式

```
data: {"type":"meta","sessionId":1,"refs":[{"newsId":12,"title":"…","score":0.83}]}
data: {"type":"delta","content":"根据资料"}
data: {"type":"reasoning","content":"…"}      # 可选，模型思考过程
data: {"type":"done","usage":{...},"latencyMs":2100}
data: [DONE]
```

## 7. 设计要点

**切分**：按句号/问号/换行等边界切 300 字、重叠 60 字，避免把一句话切断；切片记录字符偏移，便于引用溯源。

**召回**：问题向量化后与全部切片做余弦相似度（向量已 L2 归一化，点积即余弦），每篇新闻只保留最高分切片，再做相似度阈值过滤（默认 0.30）。

**降级**：模型调用失败自动重试 2 次；检索失败降级为「无资料回答」；摘要生成失败返回 503 而不是 500，前端可提示重试。

**成本控制**：
- 摘要/问答走 `deepseek-flash`，今日要闻走 `deepseek-v4-pro`
- 摘要、今日要闻结果入库缓存，二次请求零 token
- 检索结果进程内 TTL + LRU 缓存（命中率见 `/api/ai/stats`）
- 每次响应返回 `promptTokens / completionTokens / reasoningTokens / cost`

**鉴权**：JWT（HS256）
**Agent 工具调用循环（默认链路）**：
- 自主决策：不再用关键词规则分流，`mode=auto` 直接进入工具循环，由模型决定搜什么、搜几次、要不要读正文
- 5 个工具：`search_news` / `get_news_detail` / `related_news` / `summarize_news` / `finish_answer`
- **终止判断**：模型认为资料足够时调用 `finish_answer` 并给出理由；预算用尽或到达最后一轮时，会单独发起一次「终止判断」调用，仍由模型给出停止理由
- **任务模式**（`taskMode=true`）：把一句话任务拆成多个方面分别检索，输出结构化分点 + 引用
- **预算管理**：普通 3 轮 / 4 次调用，任务模式 3 轮 / 4 次调用；每次工具结果附带剩余预算提示，引导模型收敛
- 规划阶段非流式，拿到资料后用「编号化资料 + 流式生成」输出，保证引用编号与参考列表严格对应
- **引用校验**：生成后逐条校验 `[n]`，指向不存在资料的编号会被剔除并通过 `fix` 事件回传前端替换正文
- **失败回退**：任何异常（超时/400/网络）自动回退单次 RAG 并提示「已切换为快速模式」
- 前端逐步展示工具轨迹（搜了什么、几条、耗时），`sub` 存用户 id；AI 问答允许匿名，登录后会话落库可回看。

**采集策略（手动刷新）**：
- 不跑后台定时任务，只在用户点刷新 / 下拉时触发一次，避免库无限增长和后台悄悄消耗 token
- 采集源：中新网 6 个频道 + 中新网-国内 + IT之家 / 爱范儿 / Solidot / 少数派
- **回源抓正文**：RSS 只给几十字摘要，入库时若摘要 < 200 字，会并发（5 路）回源站抓全文与首图，失败则保留摘要
- 已有短正文可用 `python -m scripts.backfill_content` 批量回填
- 前端 POST `/api/news/refresh` 后立即返回，再轮询状态，不会让页面卡 8 秒
- 60 秒冷却，防止连点把四个站点各请求多遍
- 标题查重，重复条目直接跳过
- 热搜只有标题+链接，**不入向量索引**，避免一句话标题污染 RAG 答案
- 保留策略：每个来源最多 200 条、非 seed 总量上限 5000 条，每次刷新后自动清理

## 8. 实测数据（本机 378 条实时新闻）

| 场景 | 结果 |
|---|---|
| 建索引 | 3678 个切片，512 维，全量约 2 分钟（CPU） |
| 单篇摘要 | 346 tokens / ¥0.00046 / 约 2s，二次访问命中缓存 |
| RAG 问答 | 790 tokens / ¥0.00074 / 2.3s，回答带 `[1][4]` 引用 |
| 今日要闻 | 1535 tokens / ¥0.0087（pro 模型），按日期缓存 |
| 语义相关 | Top-3 召回相关新闻，相似度 0.9+ 命中同题不同源的新闻 |
| 手动刷新 | 11 个 RSS 源，3 秒抓到 54 条（去重后），7 天以外的旧闻直接丢弃 |

> 价格按 `.env` 中的估算单价计算，仅用于展示成本量级，实际以官方账单为准。
> 注：36氪 RSS 已停止输出，采集源改为爱范儿；百度热搜只有标题没有正文，已从产品中移除。

## 9. 测试

```bash
cd backend
pytest -q
```

覆盖：切分逻辑、Prompt 组装、模型路由、token 成本计算（不消耗真实 token）。

## 10. 常见问题

| 现象 | 原因 / 解决 |
|---|---|
| `TypeError: 'str' object is not callable`（aiomysql） | PyMySQL 版本过高，执行 `pip install PyMySQL==1.1.1` |
| 向量模型下载卡住 | 用 `.env` 的 `HF_ENDPOINT=https://hf-mirror.com`，或按 5.3 从 ModelScope 手动放置 onnx |
| `/api/ai/chat` 返回 503 | 未建索引或 `DEEPSEEK_API_KEY` 未配置，先跑 `build_index` |
| 端口被占用 | 后端 `--port 8001`，同时改前端 `src/config/api.js` |

## 11. 说明

- `.env` 含密钥，已被 `.gitignore` 排除；仓库里只保留 `.env.example`。
- 原项目目录未做任何修改，本目录是独立副本，可整体迁移。
