import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    // 忽略编辑器/工具产生的临时文件，避免 vite 监听崩溃（EBUSY）
    watch: {
      ignored: ['**/.*.tmpdir/**', '**/*.tmp', '**/.git/**'],
    },
    proxy: {
      // 后端接口（前端默认直连 127.0.0.1:8000，这里保留代理便于部署时切换）
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
