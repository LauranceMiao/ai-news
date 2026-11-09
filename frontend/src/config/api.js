/**
 * API 配置
 * 注意：模型 API Key 只保存在后端 .env，前端不再持有任何密钥。
 */

export const apiConfig = {
  baseURL: 'http://127.0.0.1:8000',
}

const base = apiConfig.baseURL

export const aiConfig = {
  summary: `${base}/api/ai/summary`,
  chat: `${base}/api/ai/chat`,
  daily: `${base}/api/ai/daily`,
  related: `${base}/api/ai/related`,
  stats: `${base}/api/ai/stats`,
}

export const uiConfig = {
  // 是否在界面上展示 token 与费用（部署上线建议关闭）
  showCost: false
}
