import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { api, post } from "./api";
import { useAuth } from "./Auth";
import Knowledge from "./Knowledge";
const UsageDashboard = lazy(() => import("./UsageDashboard"));
const JobData = lazy(() => import("./JobData"));
import "./admin-knowledge.css";
const views = [
  ["overview", "운영 현황"],
  ["users", "사용자"],
  ["data", "작업·데이터"],
  ["knowledge", "지식 그래프"],
  ["costs", "비용·한도"],
];
export default function Admin() {
  const auth = useAuth(),
    location = useLocation(),
    view = location.pathname.split("/")[2] || "overview";
  const [data, setData] = useState<any>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [version, setVersion] = useState(0),
    [notice, setNotice] = useState("");
  const authorized = auth.user?.role === "admin";
  const alive = useRef(true);
  const fail = (e: any) =>
    setError(e.message || "운영 요청을 처리하지 못했습니다.");
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);
  useEffect(() => {
    if (!authorized) return;
    let live = true;
    api("/api/admin/overview")
      .then((value) => live && setData(value))
      .catch((e) => live && fail(e));
    return () => {
      live = false;
    };
  }, [authorized, version]);
  async function act(path: string, payload: any = {}, after?: () => void) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await post(path, payload);
      if (alive.current) {
        after?.();
        setVersion((v) => v + 1);
      }
      return result;
    } catch (e) {
      if (alive.current) fail(e);
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  if (!authorized)
    return (
      <section className="admin-react">
        <h1>서비스 관리</h1>
        <p role="alert">관리자 권한이 필요합니다.</p>
        <a href="/">작업 공간으로 돌아가기</a>
      </section>
    );
  return (
    <div className="admin-react">
      <header className="admin-heading">
        <div>
          <span className="eyebrow">MAGI ADMIN</span>
          <h1>서비스 관리</h1>
          <p>서비스 실행, 사용자와 저장된 기록을 관리합니다.</p>
        </div>
        <a href="/">작업 공간으로 돌아가기</a>
      </header>
      <details className="admin-account">
        <summary>관리자 계정</summary>
        <p id="account-identity">사용자 ID: {auth.user?.id} · 권한: 관리자</p>
        <button
          id="account-copy"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(auth.user!.id);
              setNotice("사용자 ID를 복사했습니다.");
            } catch {
              setError("사용자 ID를 복사하지 못했습니다.");
            }
          }}
        >
          사용자 ID 복사
        </button>
      </details>
      <nav className="admin-nav" aria-label="관리자 메뉴">
        {views.map(([v, label]) => (
          <NavLink
            key={v}
            to={"/admin/" + v}
            aria-current={v === view ? "page" : undefined}
          >
            {label}
          </NavLink>
        ))}
      </nav>
      <p id="admin-error" role="alert">
        {error}
      </p>
      <p role="status">{notice}</p>
      <fieldset className="admin-content" disabled={busy} aria-busy={busy}>
        {view === "overview" && (
          <>
            <section data-admin-section="overview">
              <h2>운영 현황</h2>
              {data ? (
                <>
                  <p>
                    사용권 상태:{" "}
                    {(
                      {
                        idle: "사용 가능",
                        waiting: "답변 대기",
                        running: "처리 중",
                        recovery: "복구 확인 필요",
                      } as Record<string, string>
                    )[data.lease?.phase] || data.lease?.phase}
                  </p>
                  <button onClick={() => void act("/api/admin/stop")}>
                    현재 실행 종료 요청
                  </button>
                </>
              ) : (
                <p>운영 현황 조회 중…</p>
              )}
            </section>
            <section data-admin-section="overview">
              <h2>지식 색인 상태</h2>
              <p>{data?.embedding_status || "임베딩 오류 없음"}</p>
              <button onClick={() => void act("/api/knowledge/retry")}>
                임베딩 색인 실행
              </button>
            </section>
          </>
        )}
        {view === "users" && (
          <section data-admin-section="users">
            <h2>사용자</h2>
            <p>역할이나 한도를 저장하면 해당 계정의 기존 세션을 폐기합니다.</p>
            {data?.users?.map((user: any) => (
              <UserEditor
                key={user.id + ":" + version}
                user={user}
                onSave={(payload) => void act("/api/admin/user", payload)}
              />
            ))}
          </section>
        )}
        {view === "costs" && <Suspense fallback={<p role="status">사용량 화면을 불러오는 중…</p>}><UsageDashboard version={version} save={act} /></Suspense>}
        {view === "data" && (
          <Suspense fallback={<p role="status">작업 목록을 불러오는 중…</p>}>
            <JobData users={data?.users || []} unowned={data?.unowned || []}
              version={version} busy={busy} save={act}
              refresh={() => setVersion((v) => v + 1)} />
          </Suspense>
        )}
        {view === "knowledge" && <Knowledge admin />}
      </fieldset>
    </div>
  );
}
function UserEditor({
  user,
  onSave,
}: {
  user: any;
  onSave: (payload: any) => void;
}) {
  return (
    <form
      className="admin-user"
      onSubmit={(e) => {
        e.preventDefault();
        const f = new FormData(e.currentTarget);
        onSave({
          id: user.id,
          role: f.get("role"),
          daily_runs: Number(f.get("daily_runs")),
          daily_usd: f.get("daily_usd"),
          suspended: f.has("suspended"),
        });
      }}
    >
      <strong>{user.id}</strong>
      <label>
        계정 역할
        <select name="role" aria-label="계정 역할" defaultValue={user.role}>
          <option value="user">일반 사용자</option>
          <option value="admin">관리자</option>
        </select>
      </label>
      <label>
        일일 실행 횟수
        <input
          name="daily_runs"
          type="number"
          min="0"
          defaultValue={user.daily_runs}
        />
      </label>
      <label>
        일일 비용 US$
        <input
          name="daily_usd"
          type="number"
          min="0"
          step=".01"
          defaultValue={user.daily_usd}
        />
      </label>
      <label className="check-label">
        <input
          name="suspended"
          type="checkbox"
          defaultChecked={user.suspended}
        />
        계정 정지
      </label>
      <button>저장 및 세션 폐기</button>
    </form>
  );
}
