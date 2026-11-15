import {
  createContext,
  useContext,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api, post, configureAuth, clearRequests, ApiError } from "../../shared/api/api";
import type { ServiceStatus, Usage, User } from "../../shared/types";
import { clearAccountDrafts, copyAccountDrafts } from "../conversation/session-drafts";
import { decodeAuthInfo, decodeServiceStatus, decodeUsage, decodeUser } from "./account-response";
interface AuthState {
  publicMode: boolean;
  user: User | null;
  status: ServiceStatus;
  usage: Usage | null;
  ready: boolean;
  authenticated: boolean;
  loginAvailable: boolean;
  notice: string;
  setNotice: (value: string) => void;
  refreshStatus: () => Promise<void>;
  logout: () => Promise<void>;
  rememberLink: () => void;
}
const Context = createContext<AuthState>(null!);
export const useAuth = () => useContext(Context);
const LINK_STATE = "magi-account-link";
let guestStart: Promise<unknown> | undefined;
function startGuest() {
  // 2026-11-13: StrictMode와 중복 인증 갱신이 각각 익명 계정을 만들지 않게 한다.
  if (!guestStart) guestStart = post("/api/auth/guest", {}).finally(() => { guestStart = undefined; });
  return guestStart;
}
let guestSession: Promise<ReturnType<typeof decodeUser>> | undefined;
function synchronizedGuest() {
  if (!navigator.locks?.request) throw new Error("익명 작업 공간은 안전한 브라우저 환경이 필요합니다. 최신 브라우저에서 다시 시도해 주세요.");
  // 2026-11-15: 쿠키를 공유하는 탭은 발급과 재확인까지 같은 잠금 안에서 수행한다.
  if (!guestSession) guestSession = (async () => await navigator.locks.request("magi-guest-session", async () => {
    let actor: ReturnType<typeof decodeUser> | undefined;
    try { actor = decodeUser(await api("/api/me")); }
    catch (error) { if (!(error instanceof ApiError) || error.status !== 401) throw error; }
    if (!actor || actor.identity_kind === "guest") {
      await startGuest();
      actor = decodeUser(await api("/api/me"));
    }
    return actor;
  }))().finally(() => { guestSession = undefined; });
  return guestSession;
}
export function AuthProvider({ children }: { children: ReactNode }) {
  const [publicMode, setPublic] = useState(true),
    [user, setUser] = useState<User | null>(null),
    [status, setStatus] = useState<ServiceStatus>({ checkState: "loading" }),
    [usage, setUsage] = useState<Usage | null>(null),
    [ready, setReady] = useState(false),
    [notice, setNotice] = useState(""),
    [loginAvailable, setLoginAvailable] = useState(false);
  const [pollEpoch, setPollEpoch] = useState(0), [authEpoch, setAuthEpoch] = useState(0);
  const realtimeConnected = useRef(false);
  const resetting = useRef(false);
  const previousUser = useRef<User | null>(null);
  const statusVersion = useRef(0);
  useEffect(() => {
    const resume = (event: PageTransitionEvent) => {
      if (event.persisted) setPollEpoch((value) => value + 1);
    };
    window.addEventListener("pageshow", resume);
    return () => window.removeEventListener("pageshow", resume);
  }, []);
  const generation = useRef(0),
    currentUser = useRef(user),
    authenticated = !publicMode || !!user;
  currentUser.current = user;
  const resetSession = (logout = false) => {
    if (resetting.current) return;
    resetting.current = true;
    generation.current++;
    previousUser.current = logout ? null : currentUser.current;
    if (logout && currentUser.current) {
      try {
        clearAccountDrafts(sessionStorage, currentUser.current.id);
      } catch {
        // 저장소 접근이 막혀도 인증과 화면 정리는 계속한다.
      }
    }
    configureAuth({ publicMode: true });
    clearRequests();
    setUser(null);
    setUsage(null);
    setStatus({ checkState: "loading" });
    realtimeConnected.current = false;
    setReady(false);
    if (logout) {
      try { sessionStorage.removeItem(LINK_STATE); sessionStorage.removeItem("return-path"); }
      catch { /* 저장소 접근이 차단되어도 로그아웃을 완료한다. */ }
      if (location.pathname !== "/" || location.search) {
        history.replaceState(null, "", "/");
        window.dispatchEvent(new PopStateEvent("popstate"));
      }
    } else setNotice("세션이 만료되어 새 작업 공간을 시작합니다.");
    setAuthEpoch(value => value + 1);
  };
  const signedOut = () => resetSession();
  const rememberLink = () => {
    if (!currentUser.current) return;
    try {
      sessionStorage.setItem(LINK_STATE, JSON.stringify({ owner: currentUser.current.id, path: location.pathname + location.search }));
    } catch {
      setNotice("이 브라우저에서 작성 중인 내용은 계정 연결 후 복구되지 않을 수 있습니다.");
    }
  };
  const statusRequest = useRef<{ generation: number; pending: boolean; promise: Promise<void> } | null>(null);
  const refreshStatus = useCallback((): Promise<void> => {
    if (!publicMode || !currentUser.current) return Promise.resolve();
    const g = generation.current;
    if (statusRequest.current?.generation === g) {
      statusRequest.current.pending = true;
      return statusRequest.current.promise;
    }
    const request = { generation: g, pending: false, promise: Promise.resolve() };
    statusRequest.current = request;
    request.promise = (async () => {
      do {
        request.pending = false;
        const version = statusVersion.current;
        try {
          const value = decodeServiceStatus(await api("/api/service/status"));
          if (g === generation.current && version === statusVersion.current) setStatus({ ...value, checkState: "ready" });
        } catch {
          if (g === generation.current && version === statusVersion.current) setStatus({ checkState: "error" });
        }
      } while (request.pending && g === generation.current);
    })().finally(() => {
      if (statusRequest.current === request) statusRequest.current = null;
    });
    return request.promise;
  }, [publicMode]);
  useEffect(() => {
    let live = true;
    const g = ++generation.current;
    const valid = () => live && g === generation.current;
    (async () => {
      try {
        const info = decodeAuthInfo(await api("/api/auth/info"));
        if (!valid()) return;
        setPublic(info.public);
        setLoginAvailable(info.login_available === true);
        configureAuth({ publicMode: info.public });
        if (!info.public) return;
        try {
          let actor, synchronized = false;
          try {
            actor = decodeUser(await api("/api/me"));
          } catch (error) {
            if (!(error instanceof ApiError) || error.status !== 401) throw error;
            actor = await synchronizedGuest();
            synchronized = true;
          }
          if (!valid()) return;
          // 2026-11-13: 익명 세션은 방문할 때마다 서버 만료 시각과 쿠키를 함께 연장한다.
          if (actor.identity_kind === "guest" && !synchronized) {
            actor = await synchronizedGuest();
            if (!valid()) return;
          }
          configureAuth({ publicMode: true, csrf: actor.csrf });
          // 2026-11-13: 다른 탭의 계정 연결은 서버가 확인한 소유 범위에서만 초안을 옮긴다.
          const previous = previousUser.current;
          if (previous) {
            try {
              if (previous.id !== actor.id && previous.identity_kind === "guest" && actor.identity_kind === "google" && actor.owner_ids?.includes(previous.id)) {
                copyAccountDrafts(sessionStorage, previous.id, actor.id);
              } else if (previous.id !== actor.id) {
                clearAccountDrafts(sessionStorage, previous.id);
              }
              previousUser.current = null;
            } catch { /* 저장소가 막혀도 인증은 계속한다. */ }
          }
          const { csrf: _, ...safe } = actor;
          setUser(safe);
          // 2026-11-13: OAuth 콜백 후 기존 작업과 이 탭의 초안을 계정에 연결한다.
          const callback = new URLSearchParams(location.search).get("auth");
          if (callback === "linked" || callback === "failed") {
            let path = "/";
            try {
              const saved = JSON.parse(sessionStorage.getItem(LINK_STATE) || "null") as { owner?: unknown; path?: unknown } | null;
              if (callback === "linked" && actor.identity_kind === "google" && typeof saved?.owner === "string" && actor.owner_ids?.includes(saved.owner)) copyAccountDrafts(sessionStorage, saved.owner, actor.id);
              if (typeof saved?.path === "string" && /^\/(?:jobs\/[0-9a-f]{32})?(?:\?[^#]*)?$/.test(saved.path)) path = saved.path;
              sessionStorage.removeItem(LINK_STATE);
            } catch { /* 저장소가 막혀도 계정 연결은 유지한다. */ }
            if (callback === "failed") setNotice("Google 계정을 연결하지 못했습니다. 기존 작업 공간을 계속 사용할 수 있습니다.");
            history.replaceState(null, "", path);
            window.dispatchEvent(new PopStateEvent("popstate"));
          }
        } catch (e) {
          if (valid()) setNotice((e as Error).message);
        }
      } catch (e) {
        if (valid()) setNotice((e as Error).message);
      } finally {
        if (valid()) { resetting.current = false; setReady(true); }
      }
    })();
    window.addEventListener("signed-out", signedOut);
    return () => {
      live = false;
      generation.current++;
      window.removeEventListener("signed-out", signedOut);
    };
  }, [authEpoch]);
  useEffect(() => {
    if (!ready || !authenticated || !publicMode) return;
    let live = true;
    const g = generation.current;
    const load = async () => {
      try {
        const u = decodeUsage(await api("/api/me/usage"));
        if (live && g === generation.current) {
          setUsage(u);
        }
      } catch (e) {
        if (live) setNotice((e as Error).message);
      }
    };
    if (document.visibilityState !== "hidden") { void load(); void refreshStatus(); }
    // 2026-11-13: 실시간 연결이 있을 때 반복 상태 조회를 피하고 숨겨진 탭은 쉬게 한다.
    const statusTimer = setInterval(() => {
      if (document.visibilityState !== "hidden" && !realtimeConnected.current) void refreshStatus();
    }, 10000), usageTimer = setInterval(() => {
      if (document.visibilityState !== "hidden") void load();
    }, 60000);
    const update = (event: Event) => {
      const detail = (event as CustomEvent<unknown>).detail;
      if (detail !== undefined) {
        try {
          const value = decodeServiceStatus(detail);
          statusVersion.current++;
          setStatus({ ...value, checkState: "ready" });
          return;
        } catch { /* 잘못된 이벤트는 보이는 화면에서만 재조회한다. */ }
      }
      if (document.visibilityState !== "hidden") void refreshStatus();
    };
    const visibility = () => { if (document.visibilityState !== "hidden") { void refreshStatus(); void load(); } };
    window.addEventListener("service-status", update);
    document.addEventListener("visibilitychange", visibility);
    const stop = () => {
      live = false;
      generation.current++;
      setStatus({ checkState: "loading" });
      clearInterval(statusTimer);
      clearInterval(usageTimer);
      window.removeEventListener("service-status", update);
      document.removeEventListener("visibilitychange", visibility);
    };
    window.addEventListener("pagehide", stop);
    return () => {
      stop();
      window.removeEventListener("pagehide", stop);
    };
  }, [ready, authenticated, publicMode, pollEpoch, refreshStatus]);
  useEffect(() => {
    const update = (event: Event) => { realtimeConnected.current = (event as CustomEvent<{ connected: boolean }>).detail?.connected === true; };
    window.addEventListener("realtime-connection", update);
    return () => window.removeEventListener("realtime-connection", update);
  }, []);
  async function logout() {
    try {
      await post("/api/logout", {});
      resetSession(true);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "로그아웃하지 못했습니다. 다시 시도해 주세요.");
    }
  }
  if (!ready)
    return (
      <main className="login">
        <h1>MAGI</h1>
        <p role="status">서비스 연결 확인 중…</p>
      </main>
    );
  if (!authenticated) return <main className="login"><h1>MAGI</h1><p role="alert">{notice || "서비스에 연결할 수 없습니다."}</p><button type="button" onClick={() => { setReady(false); setAuthEpoch(value => value + 1); }}>다시 시도</button></main>;
  return (
    <Context.Provider
      value={{
        publicMode,
        user,
        status,
        usage,
        ready,
        authenticated,
        loginAvailable,
        notice,
        setNotice,
        refreshStatus,
        logout,
        rememberLink,
      }}
    >
      {children}
    </Context.Provider>
  );
}
