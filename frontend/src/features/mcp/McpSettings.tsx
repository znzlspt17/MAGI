import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { LinkSimpleIcon, PowerIcon, WarningCircleIcon } from "@phosphor-icons/react";
import { api, sensitiveMutation } from "../../shared/api/api";
import { useAuth } from "../auth/Auth";
import { WorkspaceReturnLink } from "../workspace/WorkspaceReturnLink";
import { decodeAuthorizationUrl, decodeConnection, decodeConnections, type AuthType, type McpConnection } from "./mcp-data";
import "./mcp-settings.css";

const base = "/api/mcp/connections";
const endpoint = (id: string) => base + "/" + encodeURIComponent(id);
const statusLabel: Record<McpConnection["status"], string> = {
  disconnected: "연결 확인 필요", ready: "연결됨", auth_required: "인증 필요", error: "연결 오류",
};

interface EditorProps {
  connection?: McpConnection;
  busy: boolean;
  onCancel: () => void;
  onSave: (payload: Record<string, unknown>, operationId: string) => Promise<void>;
}

function ConnectionEditor({ connection, busy, onCancel, onSave }: EditorProps) {
  const [name, setName] = useState(connection?.name ?? "");
  const [url, setUrl] = useState(connection?.url ?? "");
  const [authType, setAuthType] = useState<AuthType>(connection?.auth_type ?? "none");
  const [header, setHeader] = useState(connection?.api_key_header ?? "X-API-Key");
  const [clientId, setClientId] = useState(connection?.oauth_client_id ?? "");
  const [credential, setCredential] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [error, setError] = useState("");
  const operation = useRef<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    let address: URL;
    try { address = new URL(url); }
    catch { setError("올바른 HTTPS 서버 주소를 입력하세요."); return; }
    if (address.protocol !== "https:" || address.username || address.password) {
      setError("인증정보가 포함되지 않은 HTTPS 서버 주소를 입력하세요."); return;
    }
    const payload: Record<string, unknown> = {
      name: name.trim(), url: address.href, auth_type: authType,
      ...(authType === "api_key" ? { api_key_header: header.trim() } : {}),
      ...(authType === "oauth" ? { oauth_client_id: clientId.trim() || null } : {}),
      ...(credential && (authType === "api_key" || authType === "bearer") ? { credential } : {}),
      ...(clientSecret && authType === "oauth" ? { oauth_client_secret: clientSecret } : {}),
    };
    if (!payload.name) { setError("연결 이름을 입력하세요."); return; }
    if (authType === "api_key" && !header.trim()) { setError("API 키 헤더 이름을 입력하세요."); return; }
    const op = operation.current ?? crypto.randomUUID();
    operation.current = op;
    // 2026-11-03: 전송이 시작되면 민감 입력을 화면 상태에서 지우고 브라우저 저장소에 남기지 않는다.
    setCredential(""); setClientSecret(""); setError("");
    try { await onSave(payload, op); operation.current = null; }
    catch (e) { setError((e as Error).message || "연결을 저장하지 못했습니다."); }
  }

  function changed() { operation.current = null; }
  return <form className="mcp-editor" onSubmit={(event) => void submit(event)} onChange={changed}>
    <h3>{connection ? "연결 수정" : "새 연결"}</h3>
    <label>연결 이름<input value={name} onChange={(e) => setName(e.target.value)} required maxLength={100} /></label>
    <label>서버 주소<input type="url" value={url} onChange={(e) => setUrl(e.target.value)} required placeholder="https://example.com/mcp" /></label>
    <label>인증 방식<select value={authType} onChange={(e) => { setAuthType(e.target.value as AuthType); setCredential(""); setClientSecret(""); }}>
      <option value="none">인증 없음</option><option value="api_key">API 키 헤더</option><option value="bearer">Bearer 토큰</option><option value="oauth">OAuth</option>
    </select></label>
    {authType === "api_key" && <label>API 키 헤더 이름<input value={header} onChange={(e) => setHeader(e.target.value)} required /></label>}
    {(authType === "api_key" || authType === "bearer") && <label>{authType === "api_key" ? "API 키" : "Bearer 토큰"}
      <input type="password" value={credential} autoComplete="new-password" onChange={(e) => setCredential(e.target.value)}
        placeholder={connection?.has_credential ? "변경할 때만 입력" : "인증정보 입력"} />
    </label>}
    {authType === "oauth" && <>
      <label>OAuth 클라이언트 ID (선택)<input value={clientId} onChange={(e) => setClientId(e.target.value)} autoComplete="off" /></label>
      <label>OAuth 클라이언트 비밀번호 (선택)<input type="password" value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} autoComplete="new-password" placeholder={connection?.has_credential ? "변경할 때만 입력" : ""} /></label>
      <p>서버가 자동 등록을 지원하면 클라이언트 정보를 생략할 수 있습니다.</p>
    </>}
    <p>인증정보는 저장 후 다시 표시되지 않습니다.</p>
    {error && <p role="alert" className="mcp-error">{error}</p>}
    <div className="mcp-actions"><button type="submit" disabled={busy}>{busy ? "저장 중…" : "저장"}</button><button type="button" onClick={onCancel} disabled={busy}>취소</button></div>
  </form>;
}

export function McpSettings() {
  const auth = useAuth();
  const [connections, setConnections] = useState<McpConnection[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [oauthFailure] = useState(() => new URLSearchParams(window.location.search).get("oauth") === "failed");
  const [editing, setEditing] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [selections, setSelections] = useState<Record<string, string[]>>({});

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const items = decodeConnections(await api(base));
      setConnections(items);
      setSelections(Object.fromEntries(items.map((item) => [item.id, item.tools.filter((tool) => tool.enabled && tool.available).map((tool) => tool.name)])));
    } catch (e) { setError((e as Error).message || "연결 목록을 불러오지 못했습니다."); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { if (auth.user?.id) void load(); else setLoading(false); }, [auth.user?.id, load]);

  async function action(task: () => Promise<unknown>, message: string) {
    setBusy(true); setError(""); setNotice("");
    try { await task(); setNotice(message); await load(); }
    catch (e) { setError((e as Error).message || "요청을 처리하지 못했습니다."); }
    finally { setBusy(false); }
  }
  async function save(connection: McpConnection | undefined, payload: Record<string, unknown>, operationId: string) {
    setBusy(true); setError(""); setNotice("");
    try {
      decodeConnection(await sensitiveMutation(connection ? endpoint(connection.id) : base, connection ? "PATCH" : "POST", payload, operationId));
      setCreating(false); setEditing(null); setNotice("연결을 저장했습니다."); await load();
    } finally { setBusy(false); }
  }
  async function authorize(connection: McpConnection) {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await api(endpoint(connection.id) + "/oauth/start", { method: "POST" });
      window.location.assign(decodeAuthorizationUrl(result));
    } catch (e) { setError((e as Error).message || "인증을 시작하지 못했습니다."); setBusy(false); }
  }
  function toggleTool(connection: McpConnection, name: string, checked: boolean) {
    setSelections((old) => {
      const previous = old[connection.id] ?? [];
      return { ...old, [connection.id]: checked ? [...new Set([...previous, name])] : previous.filter((item) => item !== name) };
    });
  }

  return <main className="mcp-page">
    <a className="brand" href="/">MAGI</a>
    <header><h1>MCP 연결</h1>
      <p>외부 MCP 서버의 조회 도구를 연결합니다. 활성 연결은 새 작업에 자동 적용되며, 도구 사용 시 작업의 검색어와 인자가 해당 서비스에 전달됩니다.</p>
    </header>
    {!auth.user ? <section><p>사용자별 MCP 연결은 로그인 후 사용할 수 있습니다.</p><WorkspaceReturnLink /></section> : <>
      {error && <p role="alert" className="mcp-message mcp-error">{error}</p>}
      {oauthFailure && <p role="alert" className="mcp-message mcp-error">인증 연결에 실패했습니다. 다시 시도해 주세요.</p>}
      {notice && <p role="status" className="mcp-message">{notice}</p>}
      <div className="mcp-toolbar"><h2>내 연결</h2><button type="button" onClick={() => { setCreating(true); setEditing(null); }} disabled={busy || creating}>연결 추가</button></div>
      {creating && <section><ConnectionEditor busy={busy} onCancel={() => setCreating(false)} onSave={(payload, op) => save(undefined, payload, op)} /></section>}
      {loading ? <p role="status">연결을 불러오는 중…</p> : <>
        {!connections.length && !error && <section><p>등록된 연결이 없습니다.</p></section>}
        {connections.map((connection) => <section className="mcp-card" key={connection.id}>
          <div className="mcp-card-heading"><div><h3>{connection.name}</h3><p className="mcp-url">{connection.url}</p></div>
            <div className="mcp-status-group" aria-label="연결 상태"><span className="mcp-status"><PowerIcon size={16} aria-hidden />{connection.enabled ? "활성" : "비활성"}</span><span className="mcp-status"><LinkSimpleIcon size={16} aria-hidden />{statusLabel[connection.status]}</span></div></div>
          {connection.error && <p className="mcp-error">{connection.error}</p>}
          {editing === connection.id ? <ConnectionEditor key={connection.id} connection={connection} busy={busy} onCancel={() => setEditing(null)} onSave={(payload, op) => save(connection, payload, op)} /> : <>
            <div className="mcp-actions">
              <button type="button" disabled={busy} onClick={() => { setCreating(false); setEditing(connection.id); }}>수정</button>
              {connection.auth_type === "oauth" && <button type="button" disabled={busy} onClick={() => void authorize(connection)}>{connection.status === "auth_required" ? "다시 인증" : "OAuth 연결"}</button>}
              <button type="button" disabled={busy} onClick={() => void action(() => api(endpoint(connection.id) + "/test", { method: "POST" }), "연결과 도구 목록을 확인했습니다.")}>연결 확인 및 도구 갱신</button>
              <button type="button" disabled={busy || (!connection.enabled && (connection.status !== "ready" || !connection.tools.some((tool) => tool.enabled && tool.available)))} onClick={() => void action(() => api(endpoint(connection.id), { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: !connection.enabled }) }), connection.enabled ? "연결을 비활성화했습니다." : "연결을 활성화했습니다.")}>{connection.enabled ? "비활성화" : "활성화"}</button>
              <button type="button" disabled={busy} onClick={() => { if (window.confirm(`'${connection.name}' 연결을 삭제할까요?`)) void action(() => api(endpoint(connection.id), { method: "DELETE" }), "연결을 삭제했습니다."); }}>삭제</button>
            </div>
            <h4>사용할 도구</h4>
            <p>조회 가능 여부는 서버가 제공한 정보이며 실제 동작을 보증하지 않습니다.</p>
            {!connection.tools.length ? <p>연결 확인 후 사용 가능한 도구가 표시됩니다.</p> : <fieldset className="mcp-tools"><legend>조회 도구 선택</legend>
              {connection.tools.map((tool) => <label key={tool.name} className="mcp-tool">
                <input type="checkbox" checked={(selections[connection.id] ?? []).includes(tool.name)}
                  disabled={busy || !tool.available || !tool.read_only_hint || tool.destructive_hint}
                  onChange={(e) => toggleTool(connection, tool.name, e.target.checked)} />
                <span><strong>{tool.name}</strong>{tool.schema_changed && <em><WarningCircleIcon size={16} aria-hidden />변경됨, 다시 선택 필요</em>}
                  {(!tool.read_only_hint || tool.destructive_hint) && <em><WarningCircleIcon size={16} aria-hidden />조회 도구로 확인되지 않음</em>}
                  {!tool.available && tool.disabled_reason && <em><WarningCircleIcon size={16} aria-hidden />{tool.disabled_reason}</em>}
                  {tool.description && <small>{tool.description}</small>}</span>
              </label>)}
              <button type="button" disabled={busy} onClick={() => void action(() => api(endpoint(connection.id), { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ selected_tools: selections[connection.id] ?? [] }) }), "도구 선택을 저장했습니다.")}>도구 선택 저장</button>
            </fieldset>}
          </>}
        </section>)}
      </>}
    </>}
    <footer className="public-links"><WorkspaceReturnLink /></footer>
  </main>;
}
