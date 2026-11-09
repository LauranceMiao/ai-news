<template>
  <div class="ai-chat-container">
    <van-nav-bar title="AI 问答" fixed>
      <template #right>
        <van-icon name="replay" size="18" @click="resetChat" />
      </template>
    </van-nav-bar>

    <div class="chat-content">
      <div class="messages-container" ref="messagesContainer">
        <div
          v-for="(message, index) in messages"
          :key="index"
          :class="['message', message.role === 'user' ? 'user-message' : 'ai-message']"
        >
          <div class="message-content">
            <!-- Agent 工具调用轨迹 -->
            <div v-if="message.steps && message.steps.length" class="trace">
              <div class="trace-head">多步检索 · 调用了 {{ message.steps.length }} 次工具</div>
              <div class="trace-line" v-for="s in message.steps" :key="s.step">
                <span class="trace-dot">{{ s.step }}</span>
                <span class="trace-text">{{ s.text }}</span>
                <span class="trace-time">{{ s.latencyMs }}ms</span>
              </div>
            </div>
            <div v-if="message.notice" class="notice">{{ message.notice }}</div>

            <div v-if="message.role === 'assistant' && !message.content && message.streaming" class="typing-indicator">
              <span></span><span></span><span></span>
            </div>
            <div
              v-else
              class="md-body"
              v-html="formatMessage(message.content, message.refs)"
              @click="onCiteClick($event, message)"
            ></div>

            <!-- 引用来源 -->
            <div v-if="message.refs && message.refs.length" class="refs">
              <div class="refs-title">参考新闻（点击可查看原文）</div>
              <div
                class="ref-item"
                v-for="(ref, i) in message.refs"
                :key="ref.newsId"
                @click="goDetail(ref.newsId)"
              >
                <span class="ref-index">[{{ i + 1 }}]</span>
                <span class="ref-text">{{ ref.title }}</span>
                <span class="ref-score">{{ (ref.score * 100).toFixed(0) }}%</span>
                <van-icon name="arrow" class="ref-arrow" />
              </div>
            </div>

            <!-- Token 消耗 -->
            <div v-if="uiConfig.showCost && message.usage" class="usage">
              {{ message.usage.model }} · {{ message.usage.totalTokens }} tokens ·
              ¥{{ message.usage.cost.toFixed(4) }}
              <span v-if="message.latencyMs">· {{ (message.latencyMs / 1000).toFixed(1) }}s</span>
              <span v-if="message.usage.estimated">（估算）</span>
            </div>
          </div>
        </div>
      </div>

      <div class="quick-prompts" v-if="messages.length <= 1">
        <van-tag
          v-for="q in quickPrompts"
          :key="q"
          plain
          type="primary"
          size="medium"
          class="prompt-tag"
          @click="usePrompt(q)"
        >{{ q }}</van-tag>
      </div>

      <div class="input-container">
        <van-field
          v-model="userInput"
          rows="1"
          autosize
          type="textarea"
          placeholder="问我最近发生了什么..."
          class="chat-input"
          @keypress.enter.prevent="sendMessage"
        />
        <van-button
          type="primary"
          class="send-button"
          :disabled="isLoading || !userInput.trim()"
          @click="sendMessage"
        >
          发送
        </van-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue';
import { useRouter } from 'vue-router';
import { showToast } from 'vant';
import * as marked from 'marked';
import DOMPurify from 'dompurify';
import { aiConfig, uiConfig } from '../config/api';
import { useUserStore } from '../store/user';
import { useChatStore } from '../store/modules/chat';

const router = useRouter();
const userStore = useUserStore();
const chat = useChatStore();

// 对话记录放在 Pinia 并持久化：离开页面/刷新都不会丢，只有「重新开始」才清空
const messages = computed({
  get: () => chat.messages,
  set: (value) => { chat.messages = value; }
});
const sessionId = computed({
  get: () => chat.sessionId,
  set: (value) => { chat.sessionId = value; }
});

const userInput = ref('');
const messagesContainer = ref(null);
const isLoading = ref(false);

const quickPrompts = [
  '今天有哪些科技新闻？',
  '最近有什么值得关注的财经消息？',
  '帮我总结一下今天的头条',
];

// 渲染回答：Markdown → 清洗 → 正文里的 [1] 和《标题》都变成可点击入口
const formatMessage = (content, refs = []) => {
  if (!content) return '';
  let html = DOMPurify.sanitize(marked.parse(content), { ADD_ATTR: ['data-ref'] });
  const list = refs || [];
  if (!list.length) return html;

  // 1) 《新闻标题》→ 能对上参考新闻就加链接
  html = html.replace(/《([^》]{4,60})》/g, (match, title) => {
    const clean = title.trim();
    const index = list.findIndex((ref) => {
      const refTitle = (ref.title || '').trim();
      if (!refTitle) return false;
      return refTitle === clean || refTitle.includes(clean) || clean.includes(refTitle.slice(0, 8));
    });
    if (index < 0) return match;
    return `<a class="cite-title" data-ref="${index + 1}">《${clean}》</a>`;
  });

  // 2) [1][2] → 引用角标
  const max = list.length;
  html = html.replace(/\[(\d{1,2})\]/g, (match, num) => {
    const n = Number(num);
    if (n < 1 || n > max) return match;
    return `<a class="cite" data-ref="${n}">[${n}]</a>`;
  });

  return html;
};

// 点击正文里的引用（[1] 或《标题》）跳转到对应新闻
const onCiteClick = (event, message) => {
  const target = event.target.closest && event.target.closest('a.cite, a.cite-title');
  if (!target) return;
  event.preventDefault();
  const index = Number(target.dataset.ref) - 1;
  const ref = message.refs && message.refs[index];
  if (ref && ref.newsId) goDetail(ref.newsId);
};

const usePrompt = (q) => {
  userInput.value = q;
  sendMessage();
};

const goDetail = (id) => router.push(`/news/detail/${id}`);

const resetChat = () => {
  chat.reset();
  showToast('已开启新对话');
};

const scrollToBottom = () => {
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight;
  }
};

watch(messages, () => nextTick(scrollToBottom), { deep: true });
onMounted(async () => {
  // 按账号隔离：不同用户各自一份对话记录
  chat.loadFor(userStore.userInfo?.id ?? null);
  if (userStore.getLoginStatus && chat.messages.length <= 1) {
    await chat.loadLatestFromServer(userStore.token);
  }
  nextTick(scrollToBottom);
});

// 换账号（登录/退出）时切换到对应用户的记录
watch(
  () => userStore.userInfo?.id ?? null,
  (newId) => {
    chat.loadFor(newId);
    nextTick(scrollToBottom);
  }
);

onBeforeUnmount(() => {
  chat.persist();
});

const sendMessage = async () => {
  const question = userInput.value.trim();
  if (!question || isLoading.value) return;

  messages.value.push({ role: 'user', content: question });
  const aiMessage = { role: 'assistant', content: '', refs: [], steps: [], notice: '', usage: null, streaming: true };
  messages.value.push(aiMessage);
  userInput.value = '';
  isLoading.value = true;
  await nextTick();
  scrollToBottom();

  try {
    const headers = { 'Content-Type': 'application/json' };
    if (userStore.token) headers.Authorization = `Bearer ${userStore.token}`;

    const response = await fetch(aiConfig.chat, {
      method: 'POST',
      headers,
      body: JSON.stringify({ question, sessionId: sessionId.value }),
    });

    if (!response.ok || !response.body) {
      const text = await response.text().catch(() => '');
      throw new Error(text || `请求失败（${response.status}）`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const parts = buffer.split('\n\n');
      buffer = parts.pop() || '';

      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith('data:')) continue;
        const payload = line.slice(5).trim();
        if (payload === '[DONE]') continue;

        let event;
        try {
          event = JSON.parse(payload);
        } catch (e) {
          continue;
        }

        if (event.type === 'meta') {
          sessionId.value = event.sessionId;
          aiMessage.refs = event.refs || [];
        } else if (event.type === 'step') {
          aiMessage.steps.push(event);
          await nextTick();
          scrollToBottom();
        } else if (event.type === 'refs') {
          if (event.refs && event.refs.length) aiMessage.refs = event.refs;
        } else if (event.type === 'notice') {
          aiMessage.notice = event.message || '';
        } else if (event.type === 'delta') {
          aiMessage.content += event.content;
          await nextTick();
          scrollToBottom();
        } else if (event.type === 'done') {
          aiMessage.usage = event.usage;
          aiMessage.refs = event.refs || aiMessage.refs;
          aiMessage.latencyMs = event.latencyMs;
          if (event.sessionId) sessionId.value = event.sessionId;
        } else if (event.type === 'error') {
          aiMessage.content += `\n\n> 出错了：${event.message}`;
        }
      }
    }

    if (!aiMessage.content) {
      aiMessage.content = '抱歉，没有生成内容，请稍后再试。';
    }
  } catch (error) {
    console.error('AI 请求失败:', error);
    aiMessage.content = `请求失败：${error.message || '请检查后端服务是否启动'}`;
  } finally {
    aiMessage.streaming = false;
    isLoading.value = false;
    chat.trim();
    chat.persist();
    await nextTick();
    scrollToBottom();
  }
};
</script>

<style scoped>
.ai-chat-container {
  display: flex;
  flex-direction: column;
  height: 100vh;
  padding-top: 46px;
  padding-bottom: 50px;
  box-sizing: border-box;
}

.chat-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.messages-container {
  flex: 1;
  overflow-y: auto;
  padding: 10px;
}

.message {
  margin-bottom: 10px;
  max-width: 85%;
}

.user-message {
  margin-left: auto;
}

.ai-message {
  margin-right: auto;
}

.message-content {
  padding: 10px;
  border-radius: 10px;
  word-break: break-word;
  font-size: 15px;
  line-height: 1.6;
}

.user-message .message-content {
  background-color: #007aff;
  color: white;
}

.ai-message .message-content {
  background-color: #f4f5f7;
  color: #333;
}

.trace {
  background: #eef4ff;
  border: 1px solid #dbe7ff;
  border-radius: 8px;
  padding: 8px 10px;
  margin-bottom: 8px;
}

.trace-head {
  font-size: 11px;
  color: #6b86b8;
  margin-bottom: 4px;
}

.trace-line {
  display: flex;
  align-items: center;
  font-size: 12px;
  color: #46608f;
  line-height: 1.6;
}

.trace-dot {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #1989fa;
  color: #fff;
  font-size: 9px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-right: 6px;
  flex-shrink: 0;
}

.trace-text {
  flex: 1;
}

.trace-time {
  color: #9fb1cc;
  font-size: 11px;
  margin-left: 6px;
}

.notice {
  font-size: 12px;
  color: #e6913a;
  background: #fff7e8;
  border-radius: 6px;
  padding: 4px 8px;
  margin-bottom: 6px;
}

.refs {
  margin-top: 10px;
  border-top: 1px dashed #ddd;
  padding-top: 8px;
}

.refs-title {
  font-size: 12px;
  color: #888;
  margin-bottom: 6px;
}

.ref-item {
  display: flex;
  align-items: center;
  font-size: 13px;
  color: #1989fa;
  padding: 4px 0;
  cursor: pointer;
}

.ref-item:active {
  opacity: 0.6;
}

.ref-index {
  margin-right: 4px;
  flex-shrink: 0;
}

.ref-text {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ref-score {
  color: #bbb;
  font-size: 12px;
  margin-left: 6px;
}

.ref-arrow {
  color: #c8c9cc;
  font-size: 12px;
  margin-left: 4px;
}

/* 正文里的 [1][2] 引用标记 */
:deep(.cite) {
  color: #1989fa;
  font-weight: 500;
  text-decoration: none;
  cursor: pointer;
  padding: 0 1px;
  border-radius: 3px;
}

:deep(.cite:active) {
  background: #e8f3ff;
}

/* 正文里的《新闻标题》 */
:deep(.cite-title) {
  color: #1989fa;
  text-decoration: none;
  border-bottom: 1px dashed #9ecbff;
  cursor: pointer;
}

.usage {
  margin-top: 8px;
  font-size: 11px;
  color: #aaa;
}

.quick-prompts {
  padding: 0 12px 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.prompt-tag {
  cursor: pointer;
}

.input-container {
  display: flex;
  padding: 10px;
  border-top: 1px solid #eee;
  background-color: #fff;
}

.chat-input {
  flex: 1;
  margin-right: 10px;
}

.send-button {
  align-self: flex-end;
}

.typing-indicator {
  display: flex;
  padding: 5px;
}

.typing-indicator span {
  height: 8px;
  width: 8px;
  background-color: #999;
  border-radius: 50%;
  margin: 0 2px;
  display: inline-block;
  animation: bounce 1.5s infinite ease-in-out;
}

.typing-indicator span:nth-child(2) {
  animation-delay: 0.2s;
}

.typing-indicator span:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes bounce {
  0%, 60%, 100% { transform: translateY(0); }
  30% { transform: translateY(-5px); }
}

:deep(pre) {
  background-color: #f0f0f0;
  padding: 10px;
  border-radius: 4px;
  overflow-x: auto;
}

:deep(code) {
  font-family: monospace;
  background-color: #f0f0f0;
  padding: 2px 4px;
  border-radius: 4px;
}

:deep(p) {
  margin: 8px 0;
}

:deep(ul), :deep(ol) {
  padding-left: 20px;
}

:deep(a) {
  color: #1989fa;
  text-decoration: none;
}
/* ---- 新主题适配 ---- */
.ai-chat-container {
  background: var(--bg) !important;
  padding-top: 0 !important;
}
.ai-message .message-content {
  background: var(--bg-card) !important;
  color: var(--text) !important;
  border: 1px solid var(--border);
}
.user-message .message-content {
  background: var(--brand) !important;
  color: #fff !important;
}
.input-container {
  background: var(--bg-sidebar) !important;
  border-top: 1px solid var(--border) !important;
}
.chat-input :deep(.van-field__control),
.chat-input :deep(textarea) {
  color: var(--text) !important;
}
.md-body { color: var(--text); }
.usage, .refs-title { color: var(--text-faint) !important; }
</style>