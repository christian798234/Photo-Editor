import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Production: the build is written into the Python package and served by
// the local backend, so end users do not need Node.js.
// Development: `npm run dev` proxies /api to a backend started with
//   python -m birdedit --dev --port 8765 --token <VITE_BIRDEDIT_TOKEN>
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../backend/birdedit/web",
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: "http://127.0.0.1:8765", changeOrigin: true } },
  },
});
