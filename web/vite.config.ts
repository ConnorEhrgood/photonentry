import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 5193 is PhotonEntry's dev port: the sister products' dev servers use 5175, 5176 and 5180-5183, so none collide.
export default defineConfig({
  plugins: [react()],
  server: { port: 5193, strictPort: true, host: true },
})
