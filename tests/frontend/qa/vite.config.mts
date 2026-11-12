import { defineConfig, mergeConfig } from "../../../frontend/node_modules/vite/dist/node/index.js";
import base from "../../../frontend/vite.config";

// 검증용 진입점은 운영 번들 및 서버에 포함하지 않는다.
export default mergeConfig(base, defineConfig({
  root: "..",
  // 2026-11-12: QA 의존성 캐시가 저장소의 기존 Vite 캐시를 덮지 않게 분리한다.
  cacheDir: ".cache/chatgpt-rebuild/vite",
  base: "/",
  server: { host: "127.0.0.1", port: 5173, strictPort: true, hmr: false },
  plugins: [{ name: "qa-routes", configureServer(server) {
    server.middlewares.use((req, _res, next) => {
      if (req.headers.accept?.includes("text/html") && !req.url?.startsWith("/static/")) req.url = "/tests/frontend/qa/index.html";
      next();
    });
  } }],
}));
