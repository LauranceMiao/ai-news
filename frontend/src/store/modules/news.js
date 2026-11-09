import { defineStore } from 'pinia'
import axios from 'axios'
import { apiConfig } from '../../config/api'

const PAGE_SIZE = 10

export const useNewsStore = defineStore('news', {
  state: () => ({
    newsList: [],
    newsDetail: {},
    categories: [],
    currentCategory: 1,
    loading: false,
    refreshing: false,
    finished: false,
    categoriesLoading: false,
    // 请求序号：切换分类后，旧请求的结果直接丢弃，避免串数据
    requestSeq: 0
  }),

  actions: {
    // 获取新闻分类
    async getCategories() {
      if (this.categoriesLoading) return

      this.categoriesLoading = true

      try {
        const response = await axios.get(`${apiConfig.baseURL}/api/news/categories`)

        if (response.data && response.data.code === 200) {
          this.categories = [...response.data.data, { id: 10, name: '更多' }]

          if (!this.currentCategory && this.categories.length > 0) {
            this.currentCategory = this.categories[0].id
          }
        }
      } catch (error) {
        console.error('获取新闻分类失败:', error)
        this.categories = [
          { id: 1, name: '头条' },
          { id: 2, name: '社会' },
          { id: 3, name: '国内' },
          { id: 4, name: '国际' },
          { id: 5, name: '娱乐' },
          { id: 6, name: '体育' },
          { id: 7, name: '科技' }
        ]
      } finally {
        this.categoriesLoading = false
      }
    },

    // 获取新闻列表
    // isRefresh=true：重置列表从第 1 页拉
    async getNewsList(isRefresh = false) {
      if (this.loading && !isRefresh) return

      const seq = ++this.requestSeq
      const categoryId = this.currentCategory

      if (isRefresh) {
        this.refreshing = true
        this.newsList = []
        this.finished = false
      }

      this.loading = true

      const params = {
        categoryId,
        page: isRefresh ? 1 : Math.floor(this.newsList.length / PAGE_SIZE) + 1,
        pageSize: PAGE_SIZE
      }

      let success = false

      try {
        const response = await axios.get(`${apiConfig.baseURL}/api/news/list`, {
          params,
          timeout: 8000
        })

        // 已经切到别的分类了，这次结果作废
        if (seq !== this.requestSeq || categoryId !== this.currentCategory) return

        if (response.data && response.data.code === 200 && Array.isArray(response.data.data?.list)) {
          const list = response.data.data.list
          const merged = isRefresh ? list : [...this.newsList, ...list]

          // 按 id 去重，避免分页重叠或重复请求导致同一条出现两次
          const seen = new Set()
          this.newsList = merged.filter((item) => {
            if (!item || seen.has(item.id)) return false
            seen.add(item.id)
            return true
          })

          if (list.length < PAGE_SIZE) this.finished = true
          success = true
        }
      } catch (error) {
        console.error('获取新闻列表失败:', error)
      } finally {
        if (seq !== this.requestSeq) return

        if (!success) {
          // 接口异常时不再塞假数据（会把真实列表冲掉），只标记结束
          this.finished = true
        }

        this.loading = false
        this.refreshing = false
      }
    },

    // 获取新闻详情
    async getNewsDetail(id) {
      try {
        const response = await axios.get(`${apiConfig.baseURL}/api/news/detail?id=${id}`)
        if (response.data && response.data.code === 200) {
          this.newsDetail = response.data.data
          return
        }
        console.error('获取新闻详情失败: 接口返回错误')
      } catch (error) {
        console.error('获取新闻详情失败:', error)
      }
    },

    // 切换新闻分类
    changeCategory(categoryId) {
      if (this.currentCategory === categoryId) return
      this.currentCategory = categoryId
      this.newsList = []
      this.finished = false
      this.loading = false
      this.getNewsList(true)
    },

    // 获取分类名称
    getCategoryName(categoryId) {
      const category = this.categories.find(item => item.id === categoryId)
      return category ? category.name : '未知'
    }
  }
})
