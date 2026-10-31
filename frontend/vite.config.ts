/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development the Django API runs on :8000; in production Django serves this build.
export default defineConfig({
  // GitHub Pages serves the app from /<repo>/; Django serves it from the root.
  base: process.env.VITE_BASE_PATH ?? '/',
  plugins: [react()],
  server: {
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  build: {
    chunkSizeWarningLimit: 1200, // maplibre-gl alone is ~1 MB minified
    rolldownOptions: {
      output: {
        // Ship the map engine as its own long-cached chunk; app code changes far more often.
        codeSplitting: {
          groups: [{ name: 'maplibre', test: /node_modules[\\/]maplibre-gl/ }],
        },
      },
    },
  },
  test: {
    environment: 'node',
  },
})
