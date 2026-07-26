import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 构建产物直接输出到仓库 web/ 目录，由 FastAPI StaticFiles 托管
export default defineConfig({
  plugins: [react()],
  base: '/',
  build: {
    outDir: '../web',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
