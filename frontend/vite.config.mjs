import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  build: {
    outDir: "build",
    // Keep chunk sizes readable; editor + prism dominate
    chunkSizeWarningLimit: 900,
  },
  server: {
    port: 3000,
    proxy: {
      "/api": {
        target: process.env.VITE_DEV_API || "http://localhost:8090",
        changeOrigin: true,
        ws: true,
      },
    },
  },
});
