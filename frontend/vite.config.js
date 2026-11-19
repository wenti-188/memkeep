import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: '../web/dist',
    emptyOutDir: true,
  },
  server: {
    port: 5175,
    proxy: {
      '/api': 'http://127.0.0.1:5051',
      '/health': 'http://127.0.0.1:5051',
      '/metrics': 'http://127.0.0.1:5051',
    },
  },
})
