import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The built app is served by FastAPI (`regguard serve`) from the Python package.
const outDir = path.resolve(__dirname, "../backend/src/regguard/web");

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  build: { outDir, emptyOutDir: true },
  server: {
    host: "127.0.0.1",
    // `npm run dev` talks to `regguard serve` running on port 8000.
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: false } },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"], // e2e/ is Playwright's
  },
});
