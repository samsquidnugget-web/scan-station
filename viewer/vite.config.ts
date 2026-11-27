import { defineConfig } from "vite";

// In development (npm run dev) the backend runs separately on port 8000.
export default defineConfig({
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  build: { chunkSizeWarningLimit: 1000 },
});
