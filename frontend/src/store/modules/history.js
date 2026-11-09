import { defineStore } from 'pinia';
import axios from 'axios';
import { useUserStore } from '../user';
import { apiConfig } from '../../config/api';

export const useHistoryStore = defineStore('history', {
  state: () => ({
    history: [],
  }),
  
  getters: {
    getHistory: (state) => state.history,
  },
  
  actions: {
    // 添加浏览历史 - API请求
    async addHistoryApi(newsId) {
      const userStore = useUserStore();
      
      // 检查用户是否登录
      if (!userStore.getLoginStatus) {
        return { success: false, message: '请先登录' };
      }
      
      try {
        const response = await axios.post(`${apiConfig.baseURL}/api/history/add`, 
          { newsId },
          { 
            headers: { 
              Authorization: `Bearer ${userStore.token}` 
            } 
          }
        );
        
        if (response.data.code === 200) {
          return { success: true, data: response.data.data };
        } else {
          return { success: false, message: response.data.message || '添加浏览历史失败' };
        }
      } catch (error) {
        console.error('添加浏览历史请求失败:', error);
        return { success: false, message: '网络请求失败' };
      }
    },
    
    // 添加浏览历史 - 本地
    addHistory(news) {
      // 检查是否已存在相同ID的新闻
      const existingIndex = this.history.findIndex(item => item.id === news.id);
      
      // 如果已存在，先删除旧记录
      if (existingIndex !== -1) {
        this.history.splice(existingIndex, 1);
      }
      
      // 添加到历史记录的最前面（最新浏览的在最前面）
      this.history.unshift({
        ...news,
        viewTime: new Date().toLocaleString()
      });
      
      // 限制历史记录数量，最多保存50条
      if (this.history.length > 50) {
        this.history.pop();
      }
      
      // 保存到本地存储
      this.saveHistory();
    },
    
    // 清空浏览历史
    clearHistory() {
      this.history = [];
      this.saveHistory();
    },
    
    // 清空浏览历史 - API请求
    async clearHistoryApi() {
      const userStore = useUserStore();

      if (!userStore.getLoginStatus) {
        this.clearHistory();
        return { success: true, isLocal: true };
      }

      try {
        const response = await axios.delete(`${apiConfig.baseURL}/api/history/clear`, {
          headers: {
            Authorization: `Bearer ${userStore.token}`
          }
        });

        if (response.data.code === 200) {
          this.clearHistory();
          return { success: true };
        }
        return { success: false, message: response.data.message || '清空浏览历史失败' };
      } catch (error) {
        if (error.response && error.response.status === 401) {
          userStore.logout();
        }
        // 无论服务端成功与否，本地都清掉
        this.clearHistory();
        return { success: true, isLocal: true, message: '已清空本地记录' };
      }
    },
    
    // 删除单条浏览历史
    removeHistory(id) {
      this.history = this.history.filter(item => item.id !== id);
      this.saveHistory();
    },
    
    // 删除单条浏览历史 - API请求
    async removeHistoryApi(id) {
      const userStore = useUserStore();

      // 未登录：直接删本地
      if (!userStore.getLoginStatus) {
        this.removeHistory(id);
        return { success: true, isLocal: true };
      }

      try {
        const response = await axios.delete(`${apiConfig.baseURL}/api/history/delete/${id}`, {
          headers: {
            Authorization: `Bearer ${userStore.token}`
          }
        });

        if (response.data.code === 200) {
          this.removeHistory(id);
          return { success: true };
        }
        if (response.data.code === 404) {
          // 服务端已经没有这条了，本地也同步删掉，避免“删不掉”的错觉
          this.removeHistory(id);
          return { success: true };
        }
        return { success: false, message: response.data.message || '删除浏览历史失败' };
      } catch (error) {
        if (error.response && error.response.status === 401) {
          userStore.logout();
          this.removeHistory(id);
          return { success: true, isLocal: true, message: '登录已过期，已从本地删除' };
        }
        // 网络异常也先删本地，避免用户以为按钮没反应
        this.removeHistory(id);
        return { success: true, isLocal: true, message: '网络异常，已从本地删除' };
      }
    },
    
    // 保存到本地存储
    saveHistory() {
      localStorage.setItem('news_history', JSON.stringify(this.history));
    },
    
    // 从本地存储加载
    loadHistory() {
      const savedHistory = localStorage.getItem('news_history');
      if (savedHistory) {
        this.history = JSON.parse(savedHistory);
      }
    },
    
    // 获取浏览历史 - API请求
    async getHistoryListApi() {
      const userStore = useUserStore();
      
      // 检查用户是否登录
      if (!userStore.getLoginStatus) {
        return { success: false, message: '未登录', isLocal: true };
      }
      
      try {
        const response = await axios.get(`${apiConfig.baseURL}/api/history/list`, { 
          params: { page: 1, pageSize: 50 },
          headers: { 
            Authorization: `Bearer ${userStore.token}` 
          } 
        });
        
        if (response.data.code === 200) {
          this.history = response.data.data.list || [];
          this.saveHistory();
          return { success: true, data: this.history };
        }
        return { success: false, message: response.data.message || '获取浏览历史失败' };
      } catch (error) {
        // token 失效（比如换了鉴权方式）：清掉登录态，退回本地历史
        if (error.response && error.response.status === 401) {
          userStore.logout();
          return { success: false, message: '登录已过期', isAuthFailed: true, isLocal: true };
        }
        return { success: false, message: '网络请求失败', isLocal: true };
      }
    },
  },
});