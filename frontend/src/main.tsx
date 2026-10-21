import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "./Auth";
import Workspace from "./Workspace";
import Admin from "./Admin";
import "./theme.css";
import "./styles.css";
import "./workspace-design.css";
import "./chat-design.css";
import { Licenses } from "./Licenses";
export function Privacy() {
  return (
    <main className="privacy">
      <a className="brand" href="/">
        MAGI
      </a>
      <span className="eyebrow">PRIVACY</span>
      <h1>MAGI 정보 처리 안내</h1>
      <p>
        이름·이메일·프로필을 요청하지 않습니다. 로그인에는 계정 구분용 식별
        정보와 인증 세션만 사용합니다.
      </p>
      <p>
        명세 생성을 위해 작성한 요청과 답변은 AI 제공자에게 전송됩니다. 민감한
        정보나 비밀값을 입력하지 마세요.
      </p>
      <p>
        작업 기록과 문서는 본인 계정에 보관됩니다. 기록 삭제는 관리자에게
        요청하세요. 백업 보존·삭제 기간과 운영자 연락처는 공개 전 운영 문서에
        확정해야 합니다.
      </p>
      <div className="public-links"><a href="/">돌아가기</a><a href="/licenses">오픈소스 라이선스</a></div>
    </main>
  );
}
function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/privacy" element={<Privacy />} />
        <Route path="/licenses" element={<Licenses />} />
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
