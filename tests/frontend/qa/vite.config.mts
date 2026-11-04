import { defineConfig, mergeConfig } from "../../../frontend/node_modules/vite/dist/node/index.js";
import base from "../../../frontend/vite.config";

// 검증용 진입점은 운영 번들 및 서버에 포함하지 않는다.
export default mergeConfig(base, defineConfig({
  root: "..",
  base: "/",
  server: { host: "127.0.0.1", port: 5173, strictPort: true, hmr: false },
  plugins: [{ name: "qa-routes", configureServer(server) {
    server.middlewares.use((req, _res, next) => {
      if (req.headers.accept?.includes("text/html") && !req.url?.startsWith("/static/")) req.url = "/tests/frontend/qa/index.html";
      next();
    });
  } }],
}));
