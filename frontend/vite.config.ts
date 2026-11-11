import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";
import { resourcesAndNotices } from "./scripts/notices.mjs";
import { fileURLToPath, URL } from "node:url";
export default defineConfig({
  envDir: false,
  esbuild: { jsx: "automatic" },
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  plugins: [tailwindcss(), resourcesAndNotices(), {
    name: "test-dependencies",
    // 2026-11-04: 저장소 루트에 둔 테스트도 프론트엔드의 설치 의존성을 사용한다.
    async resolveId(source, importer) {
      if (importer?.replaceAll("\\", "/").includes("/tests/frontend/src/") && !source.startsWith(".") && !source.startsWith("@/")) {
        return this.resolve(source, fileURLToPath(new URL("./src/main.tsx", import.meta.url)), { skipSelf: true });
      }
    },
  }],
  base: "/static/dist/",
  build: {
    outDir: "static/dist",
    emptyOutDir: true,
    manifest: "manifest.json",
    rollupOptions: { input: "src/main.tsx" },
  },
  test: { environment: "jsdom", globals: true, setupFiles: [fileURLToPath(new URL("../tests/frontend/setup.ts", import.meta.url))], include: ["tests/frontend/src/**/*.test.{ts,tsx}"] },
});
