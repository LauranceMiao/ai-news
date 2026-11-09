import { defineStore } from 'pinia'

const WELCOME = {
  role: 'assistant',
  content: '你好，我是新闻 AI 助手。你可以问我「今天科技圈有什么大事」，我会基于站内新闻回答并给出出处。'
}

const STORAGE_PREFIX = 'news-ai-chat:'

function storageKey(ownerId) {
  return `${STORAGE_PREFIX}${ownerId === null || ownerId === undefined ? 'anon' : ownerId}`
}

/**
 * AI 对话状态按「用户」隔离存本地：
 * - 登录用户各存各的（key 带 userId），换账号不会串；
 * - 未登录用独立的 anon 空间；
 * - 只有点「重新开始」才清空当前账号的记录。
 */
export const useChatStore = defineStore('chat', {
  state: () => ({
    messages: [{ ...WELCOME }],
    sessionId: null,
    ownerId: undefined // undefined = 还没加载过
  }),

  actions: {
    loadFor(ownerId) {
      if (this.ownerId === ownerId) return
      this.ownerId = ownerId

      // 清掉旧版本遗留的全局 key，避免串号
      localStorage.removeItem('news-ai-chat')

      const raw = localStorage.getItem(storageKey(ownerId))
      if (raw) {
        try {
          const data = JSON.parse(raw)
          this.messages = Array.isArray(data.messages) && data.messages.length
            ? data.messages
            : [{ ...WELCOME }]
          this.sessionId = data.sessionId ?? null
        } catch (error) {
          this.messages = [{ ...WELCOME }]
          this.sessionId = null
        }
      } else {
        this.messages = [{ ...WELCOME }]
        this.sessionId = null
      }
      this.sanitize()
    },

    persist() {
      if (this.ownerId === undefined) return
      try {
        localStorage.setItem(storageKey(this.ownerId), JSON.stringify({
          messages: this.messages,
          sessionId: this.sessionId
        }))
      } catch (error) {
        console.warn('保存对话失败', error)
      }
    },

    reset() {
      this.messages = [{ ...WELCOME }]
      this.sessionId = null
      this.persist()
    },

    // 页面重新进入时，把上次没走完的“正在输入”状态复位
    sanitize() {
      this.messages.forEach((m) => {
        m.streaming = false
      })
    },

    // 只保留最近 N 条，避免 localStorage 越存越大
    trim(max = 60) {
      if (this.messages.length > max) {
        this.messages = this.messages.slice(-max)
      }
    },

    // 换设备登录时，从服务端拉最近一次会话，补上本地没有的历史
    async loadLatestFromServer(token) {
      if (!token) return
      try {
        const res = await fetch('http://127.0.0.1:8000/api/ai/sessions', {
          headers: { Authorization: `Bearer ${token}` }
        })
        const data = await res.json()
        const sessions = data?.data || []
        if (!sessions.length) return

        const latest = sessions[0]
        const msgRes = await fetch(
          `http://127.0.0.1:8000/api/ai/sessions/${latest.id}/messages`,
          { headers: { Authorization: `Bearer ${token}` } }
        )
        const msgData = await msgRes.json()
        const list = msgData?.data || []
        if (!list.length) return

        this.sessionId = latest.id
        this.messages = [
          { ...WELCOME },
          ...list.map((m) => ({
            role: m.role,
            content: m.content,
            refs: m.refs || [],
            steps: m.steps || []
          }))
        ]
        this.persist()
      } catch (error) {
        console.warn('拉取历史会话失败', error)
      }
    }
  }
})
