import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      // В dev проксируем /api на бэкенд (пути на бэкенде тоже начинаются с /api — без rewrite)
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
