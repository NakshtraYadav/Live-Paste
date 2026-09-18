import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = fileURLToPath(new URL(".", import.meta.url));

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(rootDir, "src"),
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
  test: {
    environment: "jsdom",
    setupFiles: "./src/test-setup.js",
    globals: true,
  },
});
