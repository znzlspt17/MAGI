import { LoginForm } from "./components/LoginForm";
import {
  createContext,
  useContext,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api, post, configureAuth, clearRequests, ApiError } from "./api";
import type { ServiceStatus, Usage, User } from "./types";
import { clearAccountDrafts } from "./session-drafts";
interface AuthState {
  publicMode: boolean;
  user: User | null;
  status: ServiceStatus;
  usage: Usage | null;
  ready: boolean;
  authenticated: boolean;
  notice: string;
  setNotice: (value: string) => void;
  refreshStatus: () => Promise<void>;
  logout: () => Promise<void>;
}
const Context = createContext<AuthState>(null!);
export const useAuth = () => useContext(Context);
export function AuthProvider({ children }: { children: ReactNode }) {
  const [publicMode, setPublic] = useState(true),
    [user, setUser] = useState<User | null>(null),
    [status, setStatus] = useState<ServiceStatus>({ checkState: "loading" }),
    [usage, setUsage] = useState<Usage | null>(null),
    [ready, setReady] = useState(false),
    [notice, setNotice] = useState(""),
    [loginAvailable, setLoginAvailable] = useState(false);
  const [pollEpoch, setPollEpoch] = useState(0);
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
  const signedOut = () => {
    generation.current++;
    if (currentUser.current) {
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
    if (/^\/jobs\/[0-9a-f]{32}$/.test(location.pathname))
      sessionStorage.setItem("return-path", location.pathname);
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
        try {
          const value = await api<ServiceStatus>("/api/service/status");
          if (g === generation.current) setStatus({ ...value, checkState: "ready" });
        } catch {
          if (g === generation.current) setStatus({ checkState: "error" });
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
        const info = await api("/api/auth/info");
        if (!valid()) return;
        setPublic(info.public);
        setLoginAvailable(info.login_available);
        configureAuth({ publicMode: info.public });
        if (!info.public) return;
        try {
          const actor = await api<User>("/api/me");
          if (!valid()) return;
          configureAuth({ publicMode: true, csrf: actor.csrf });
          const { csrf: _, ...safe } = actor;
          setUser(safe);
          const path = sessionStorage.getItem("return-path");
          if (
            location.pathname === "/" &&
            /^\/jobs\/[0-9a-f]{32}$/.test(path || "")
          )
            location.replace(path!);
          sessionStorage.removeItem("return-path");
        } catch (e) {
          // 미로그인 응답은 정상적인 로그인 진입이므로 오류로 표시하지 않는다.
          if (live && !(e instanceof ApiError && e.status === 401)) setNotice((e as Error).message);
        }
      } catch (e) {
        if (live) setNotice((e as Error).message);
      } finally {
        if (live) setReady(true);
      }
    })();
    window.addEventListener("signed-out", signedOut);
    return () => {
      live = false;
      generation.current++;
      window.removeEventListener("signed-out", signedOut);
    };
  }, []);
  useEffect(() => {
    if (!ready || !authenticated || !publicMode) return;
    let live = true;
    const g = generation.current;
    const load = async () => {
      try {
        const u = await api<Usage>("/api/me/usage");
        if (live && g === generation.current) {
          setUsage(u);
        }
      } catch (e) {
        if (live) setNotice((e as Error).message);
      }
    };
    void load();
    void refreshStatus();
    const statusTimer = setInterval(
        () => void refreshStatus().catch((e) => live && setNotice(e.message)),
        2000,
      ),
      usageTimer = setInterval(() => void load(), 30000);
    const update = () => { void refreshStatus(); };
    window.addEventListener("service-status", update);
    const stop = () => {
      live = false;
      generation.current++;
      setStatus({ checkState: "loading" });
      clearInterval(statusTimer);
      clearInterval(usageTimer);
      window.removeEventListener("service-status", update);
    };
    window.addEventListener("pagehide", stop);
    return () => {
      stop();
      window.removeEventListener("pagehide", stop);
    };
  }, [ready, authenticated, publicMode, pollEpoch, refreshStatus]);
  async function logout() {
    try {
      await post("/api/logout", {});
    } finally {
      signedOut();
    }
  }
  if (!ready)
    return (
      <main className="login">
        <h1>MAGI</h1>
        <p role="status">서비스 연결 확인 중…</p>
      </main>
    );
  if (!authenticated) return <LoginForm available={loginAvailable} notice={notice} />;
  return (
    <Context.Provider
      value={{
        publicMode,
        user,
        status,
        usage,
        ready,
        authenticated,
        notice,
        setNotice,
        refreshStatus,
        logout,
      }}
    >
      {children}
    </Context.Provider>
  );
}
