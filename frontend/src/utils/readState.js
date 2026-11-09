// 已读状态：存在 localStorage，首页「只看未读」用它过滤
const KEY = 'read-news'

export function getReadIds() {
  try {
    const raw = localStorage.getItem(KEY)
    const list = raw ? JSON.parse(raw) : []
    return Array.isArray(list) ? list : []
  } catch (error) {
    return []
  }
}

export function markRead(id) {
  if (!id) return
  const ids = getReadIds()
  if (ids.includes(id)) return
  ids.unshift(id)
  // 只留最近 500 条，避免无限增长
  localStorage.setItem(KEY, JSON.stringify(ids.slice(0, 500)))
}

export function isRead(id) {
  return getReadIds().includes(id)
}
