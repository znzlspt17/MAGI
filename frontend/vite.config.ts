import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";
import { resourcesAndNotices } from "./scripts/notices.mjs";
import { fileURLToPath, URL } from "node:url";
export default defineConfig({
  envDir: false,
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  plugins: [tailwindcss(), resourcesAndNotices()],
  base: "/static/dist/",
  build: {
    outDir: "static/dist",
    emptyOutDir: true,
    manifest: "manifest.json",
    rollupOptions: { input: "src/main.tsx" },
  },
  test: { environment: "jsdom", globals: true },
});
