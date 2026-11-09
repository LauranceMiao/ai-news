import { defineStore } from 'pinia'

const STORAGE_KEY = 'theme-mode'

export const useThemeStore = defineStore('theme', {
  state: () => ({
    // dark / light
    mode: localStorage.getItem(STORAGE_KEY) || 'dark'
  }),

  getters: {
    isDark: (state) => state.mode === 'dark',
    label: (state) => (state.mode === 'dark' ? '深色' : '浅色')
  },

  actions: {
    apply() {
      document.documentElement.setAttribute('data-theme', this.mode)
      document.documentElement.style.colorScheme = this.mode
    },

    setMode(mode) {
      this.mode = mode === 'light' ? 'light' : 'dark'
      localStorage.setItem(STORAGE_KEY, this.mode)
      this.apply()
    },

    toggle() {
      this.setMode(this.mode === 'dark' ? 'light' : 'dark')
    },

    initTheme() {
      this.apply()
    }
  }
})
