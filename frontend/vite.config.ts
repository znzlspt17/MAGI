import { defineConfig } from "vite";
export default defineConfig({
  base: "/static/dist/",
  build: {
    outDir: "static/dist",
    emptyOutDir: true,
    manifest: "manifest.json",
    rollupOptions: { input: "src/main.tsx" },
  },
  test: { environment: "jsdom", globals: true },
});
