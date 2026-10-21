import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { api, post } from "./api";
import { useAuth } from "./Auth";
import { Markdown, statusLabel } from "./UI";
import Knowledge from "./Knowledge";
const UsageDashboard = lazy(() => import("./UsageDashboard"));
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
    [catalog, setCatalog] = useState<any>({ jobs: [], pending: [] }),
    [query, setQuery] = useState(""),
    [status, setStatus] = useState(""),
    [selected, setSelected] = useState(new Set<string>()),
    [jobId, setJobId] = useState(""),
    [ownerId, setOwnerId] = useState(""),
    [ownerJobs, setOwnerJobs] = useState<any[]>([]),
    [ownerLoading, setOwnerLoading] = useState(false),
    [ownerError, setOwnerError] = useState(""),
    [job, setJob] = useState<any>(null),
    [operation, setOperation] = useState<any>(null),
    [confirmation, setConfirmation] = useState(""),
    [cleanupError, setCleanupError] = useState(""),
    [notice, setNotice] = useState("");
  const alive = useRef(true),
    jobRequest = useRef(0),
    dialog = useRef<HTMLDialogElement>(null),
    authorized = auth.user?.role === "admin";
  const fail = (e: any) =>
    setError(e.message || "운영 요청을 처리하지 못했습니다.");
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      jobRequest.current++;
    };
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
  useEffect(() => {
    if (!authorized || view !== "data") return;
    let live = true;
    api("/api/admin/cleanup/catalog")
      .then((value) => {
        if (live) {
          setCatalog(value);
          setSelected(new Set());
        }
      })
      .catch((e) => live && fail(e));
    return () => {
      live = false;
    };
  }, [authorized, view, version]);
  useEffect(() => {
    if (!authorized || view !== "data" || !ownerId) return;
    let live = true;
    setOwnerLoading(true);
    setOwnerError("");
    setOwnerJobs([]);
    api("/api/admin/user_jobs?owner_id=" + encodeURIComponent(ownerId))
      .then((value) => live && setOwnerJobs(value))
      .catch((e) => live && setOwnerError(e.message || "사용자 작업을 조회하지 못했습니다."))
      .finally(() => live && setOwnerLoading(false));
    return () => { live = false; };
  }, [authorized, view, ownerId, version]);
  useEffect(() => {
    if (!operation) return;
    const opener = document.activeElement as HTMLElement | null;
    dialog.current?.showModal();
    return () => {
      if (opener?.isConnected) opener.focus();
    };
  }, [operation]);
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
  async function inspect(id: string) {
    const ticket = ++jobRequest.current;
    setError("");
    try {
      const value = await api(
        "/api/admin/job?id=" + encodeURIComponent(id.trim()),
      );
      if (ticket === jobRequest.current && alive.current) {
        setJob(value);
        setJobId(id);
      }
    } catch (e) {
      if (ticket === jobRequest.current && alive.current) fail(e);
    }
  }
  const linkedJobId = new URLSearchParams(location.search).get("job_id");
  useEffect(() => {
    if (authorized && view === "data" && linkedJobId) void inspect(linkedJobId);
    return () => { jobRequest.current++; };
  }, [authorized, view, linkedJobId]);
  async function preview(scope: string) {
    if (scope === "jobs" && !selected.size) {
      setError("삭제할 작업을 선택하세요.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const value = await post("/api/admin/cleanup/preview", {
        scope,
        ids: scope === "jobs" ? [...selected] : [],
      });
      if (alive.current) {
        setOperation(value);
        setConfirmation("");
        setCleanupError("");
      }
    } catch (e) {
      if (alive.current) fail(e);
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  async function execute(id: string, confirm = confirmation) {
    setBusy(true);
    setCleanupError("");
    setError("");
    try {
      const result = await post("/api/admin/cleanup/execute", {
        id,
        confirmation: confirm,
      });
      if (!alive.current) return;
      const deleted = operation?.targets || [];
      setOperation(null);
      setJob(null);
      setSelected(new Set());
      setNotice(
        result.state === "completed"
          ? "정리를 완료했습니다."
          : "파일 정리가 남았습니다. 재시도하세요.",
      );
      setVersion((v) => v + 1);
      window.dispatchEvent(
        new CustomEvent("magi:cleanup", { detail: { ids: deleted } }),
      );
    } catch (e) {
      if (alive.current) {
        if (operation) setCleanupError((e as Error).message);
        else fail(e);
      }
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
  const jobs = catalog.jobs.filter(
    (j: any) =>
      (!status || j.status === status) &&
      `${j.request || ""} ${j.id}`.toLowerCase().includes(query.toLowerCase()),
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
          <>
            <section data-admin-section="data">
              <h2>소유자 없는 기록</h2>
              <h3>이관 전 기록</h3>
              {data?.unowned?.length === 0 && (
                <p>소유자 없는 기록이 없습니다.</p>
              )}
              {data?.unowned?.map((j: any) => (
                <form
                  className="admin-form"
                  key={j.id}
                  onSubmit={(e) => {
                    e.preventDefault();
                    void act("/api/admin/claim", {
                      id: j.id,
                      owner_id: new FormData(e.currentTarget).get("owner_id"),
                    });
                  }}
                >
                  <code>{j.id}</code>
                  <label>
                    소유 사용자 ID
                    <input name="owner_id" required />
                  </label>
                  <button>소유자 지정</button>
                </form>
              ))}
            </section>
            <section data-admin-section="data">
              <h2 id="job-title">작업 조회</h2>
              <label>
                사용자별 작업 조회
                <select value={ownerId} onChange={(e) => {
                  setOwnerId(e.target.value);
                  setOwnerJobs([]);
                  setOwnerError("");
                  setJob(null);
                  jobRequest.current++;
                }}>
                  <option value="">사용자를 선택하세요</option>
                  {data?.users?.map((user: any) => (
                    <option key={user.id} value={user.id}>{user.id}</option>
                  ))}
                </select>
              </label>
              {ownerId && (
                <div aria-label="사용자 작업 목록">
                  {ownerLoading ? <p role="status">작업 조회 중…</p> : ownerError ? (
                    <p role="alert">{ownerError}</p>
                  ) : ownerJobs.length === 0 ? <p>이 사용자의 작업이 없습니다.</p> : (
                    <>
                      <p>작업 {ownerJobs.length}개</p>
                      {ownerJobs.map((item) => (
                        <div className="cleanup-row" key={item.id}>
                          <span>{item.request || "작업"} · {statusLabel(item.status)} · {item.id}</span>
                          <button onClick={() => void inspect(item.id)}>상세 조회</button>
                        </div>
                      ))}
                    </>
                  )}
                </div>
              )}
              <form
                id="job-form"
                className="admin-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  void inspect(jobId);
                }}
              >
                <label>
                  작업 ID
                  <input
                    id="job-id"
                    value={jobId}
                    onChange={(e) => setJobId(e.target.value)}
                    required
                  />
                </label>
                <button>조회</button>
              </form>
              <div id="job-result" tabIndex={0} aria-label="작업 상세">
                {job && (
                  <>
                    <h3>{job.request || job.id}</h3>
                    <p>작업 ID: {job.id}</p>
                    <p>상태: {statusLabel(job.status)}</p>
                    <p>소유자: {job.owner_id || "미지정"}</p>
                    {[
                      ["최종 명세", job.final],
                      ["초안", job.candidate],
                      ["보완 보고서", job.critical],
                    ].map(
                      ([label, value]) =>
                        typeof value === "string" && (
                          <details key={label}>
                            <summary>{label}</summary>
                            <Markdown content={value} />
                          </details>
                        ),
                    )}
                    {job.session_events?.length > 0 && (
                      <details>
                        <summary>처리 이력</summary>
                        {job.session_events.map((e: any, i: number) => (
                          <p key={i}>
                            {e.action} · {statusLabel(e.status)}
                          </p>
                        ))}
                      </details>
                    )}
                  </>
                )}
              </div>
            </section>
            <section data-admin-section="data">
              <h2 id="cleanup-title">데이터 삭제 및 복구 정리</h2>
              <div className="admin-form">
                <label>
                  작업 검색
                  <input
                    id="cleanup-query"
                    type="search"
                    value={query}
                    onChange={(e) => {
                      setQuery(e.target.value);
                      setSelected(new Set());
                    }}
                  />
                </label>
                <label>
                  상태
                  <select
                    id="cleanup-status"
                    value={status}
                    onChange={(e) => {
                      setStatus(e.target.value);
                      setSelected(new Set());
                    }}
                  >
                    <option value="">전체 상태</option>
                    <option value="FINALIZED">최종 완료</option>
                    <option value="error">오류</option>
                    <option value="NEEDS_USER_INPUT">확인 필요</option>
                  </select>
                </label>
                <label className="check-label">
                  <input
                    id="cleanup-select-all"
                    type="checkbox"
                    checked={
                      jobs.length > 0 &&
                      jobs.every((j: any) => selected.has(j.id))
                    }
                    onChange={(e) =>
                      setSelected(
                        e.target.checked
                          ? new Set(jobs.map((j: any) => j.id))
                          : new Set(),
                      )
                    }
                  />
                  현재 목록 전체 선택
                </label>
                <button
                  id="cleanup-refresh"
                  onClick={() => setVersion((v) => v + 1)}
                >
                  목록 새로고침
                </button>
              </div>
              <div id="cleanup-list">
                {jobs.map((j: any) => (
                  <div className="cleanup-row" key={j.id}>
                    <label className="check-label">
                      <input
                        type="checkbox"
                        value={j.id}
                        checked={selected.has(j.id)}
                        onChange={(e) =>
                          setSelected((current) => {
                            const next = new Set(current);
                            e.target.checked
                              ? next.add(j.id)
                              : next.delete(j.id);
                            return next;
                          })
                        }
                      />
                      <span>
                        {j.request || "작업"} · {j.status || ""} · {j.id}
                      </span>
                    </label>
                    <button onClick={() => void inspect(j.id)}>
                      상세 조회
                    </button>
                  </div>
                ))}
              </div>
              <div className="button-row">
                <button
                  id="cleanup-selected"
                  disabled={!selected.size}
                  onClick={() => void preview("jobs")}
                >
                  선택 작업 삭제 미리보기
                </button>
                <button
                  id="cleanup-all"
                  className="danger"
                  onClick={() => void preview("all")}
                >
                  전체 기록 삭제 미리보기
                </button>
              </div>
              <div id="cleanup-pending">
                {catalog.pending.map((id: string) => (
                  <button key={id} onClick={() => void execute(id, "")}>
                    남은 파일 정리 재시도 · {id}
                  </button>
                ))}
              </div>
              <p id="cleanup-notice" role="status">
                {notice}
              </p>
            </section>
          </>
        )}
        {view === "knowledge" && <Knowledge admin />}
      </fieldset>
      {operation && (
        <dialog
          ref={dialog}
          id="cleanup-dialog"
          onCancel={(e) => {
            if (busy) e.preventDefault();
            else setOperation(null);
          }}
          aria-labelledby="cleanup-dialog-title"
        >
          <h2 id="cleanup-dialog-title">영구 삭제 확인</h2>
          <pre id="cleanup-summary">{`대상 작업 ${operation.counts.jobs}개 · 파일 ${operation.counts.files || 0}개\n${(operation.targets || [...selected]).join("\n")}\n다른 작업의 출처 연결 ${operation.external_references || 0}개 제거 · 제외 폴더 ${(operation.skipped || []).length}개\n삭제한 기록은 복구할 수 없습니다. 미리보기는 10분 동안 유효합니다.`}</pre>
          {operation.scope === "all" && (
            <label id="cleanup-confirm-label">
              계속하려면 “전체 기록 삭제”를 입력하세요.
              <input
                id="cleanup-confirm"
                value={confirmation}
                autoComplete="off"
                onChange={(e) => setConfirmation(e.target.value)}
              />
            </label>
          )}
          <p id="cleanup-error" role="alert">
            {cleanupError}
          </p>
          <div className="button-row">
            <button
              id="cleanup-cancel"
              autoFocus
              disabled={busy}
              onClick={() => setOperation(null)}
            >
              취소
            </button>
            <button
              id="cleanup-execute"
              className="danger"
              disabled={
                busy ||
                (operation.scope === "all" && confirmation !== "전체 기록 삭제")
              }
              onClick={() => void execute(operation.id)}
            >
              영구 삭제
            </button>
          </div>
        </dialog>
      )}
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
