import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "./features/auth/Auth";
import Workspace from "./features/workspace/Workspace";
import Admin from "./features/admin/Admin";
import "./app/theme.css";
import "./app/styles.css";
import "./features/workspace/workspace-design.css";
import "./features/conversation/chat-design.css";
import "./app/compact.css";
import "./app/scrollbars.css";
import { Research } from "./features/legal/Research";
import { Licenses } from "./features/legal/Licenses";
import { WorkspaceReturnLink } from "./features/workspace/WorkspaceReturnLink";
import { McpSettings } from "./features/mcp/McpSettings";

export function Privacy() {
  return (
    <main className="privacy">
      <a className="brand" href="/">
        MAGI
      </a>
      <h1>MAGI 정보 처리 안내</h1>
      <nav aria-label="정보 처리 안내 목차" className="privacy-toc"><a href="#privacy-account">계정과 로그인</a><a href="#privacy-transmission">AI 처리</a><a href="#privacy-storage">기록 보관과 삭제</a><a href="#privacy-contact">문의</a></nav>
      <section aria-labelledby="privacy-account"><h2 id="privacy-account">계정과 로그인</h2>
      <p>
        MAGI는 Google 로그인 시 이름·이메일·프로필 사진을 요청하지 않습니다.
        Google이 제공하는 계정 식별 정보를 해시 처리하여 이용자를 구분하고,
        인증 세션을 사용해 로그인 상태를 유지합니다.
      </p>
      </section>
      <section aria-labelledby="privacy-transmission"><h2 id="privacy-transmission">AI 처리</h2>
      <p>
        입력한 요청, 질문에 대한 답변, 수정 의견과 명세 생성에 필요한 관련
        내용은 AI 처리를 위해 OpenAI에 전송됩니다. 개인정보, 비밀번호, API 키
        등 민감한 정보나 비밀값을 입력하지 마세요.
      </p>
      </section>
      <section aria-labelledby="privacy-storage"><h2 id="privacy-storage">기록 보관과 삭제</h2>
      <p>
        입력한 내용, 작업 기록과 생성된 문서는 MAGI 운영자가 관리하는 서버와
        데이터베이스에 저장됩니다. 저장된 기록은 로그인 계정의 내부 식별자와
        연결되어 이용자별로 구분되며, 작업 이어하기와 기록·문서 조회에
        사용됩니다.
      </p>
      <p>
        로그아웃해도 저장된 기록은 삭제되지 않습니다. 기록 삭제가 필요한 경우
        관리자에게 요청하세요.
      </p>
      </section>
      <section aria-labelledby="privacy-contact"><h2 id="privacy-contact">문의</h2>
      <p>
        연락처 znzlsit@naver.com
      </p>
      </section>
      <div className="public-links"><WorkspaceReturnLink /><a href="/licenses">오픈소스 라이선스</a><a href="/research">연구 출처 및 적용 방식</a></div>
    </main>
  );
}
function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/settings/mcp" element={<AuthProvider><McpSettings /></AuthProvider>} />
        <Route path="/privacy" element={<Privacy />} />
        <Route path="/licenses" element={<Licenses />} />
        <Route path="/research" element={<Research />} />
        <Route
          path="/admin/*"
          element={
            <AuthProvider>
              <Admin />
            </AuthProvider>
          }
        />
        <Route
          path="/"
          element={
            <AuthProvider>
              <Workspace />
            </AuthProvider>
          }
        />
        <Route
          path="/jobs/:id"
          element={
            <AuthProvider>
              <Workspace />
            </AuthProvider>
          }
        />
      </Routes>
    </BrowserRouter>
  );
}
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
