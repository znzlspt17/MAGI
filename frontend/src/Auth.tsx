import { LoginForm } from "./components/LoginForm";
import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api, post, configureAuth, clearRequests } from "./api";
import type { ServiceStatus, Usage, User } from "./types";
import { clearAccountDrafts } from "./storage-migration";
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
    [status, setStatus] = useState<ServiceStatus>({}),
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
    setStatus({});
    if (/^\/jobs\/[0-9a-f]{32}$/.test(location.pathname))
      sessionStorage.setItem("return-path", location.pathname);
  };
  const refreshStatus = async () => {
    if (!publicMode) return;
    const g = generation.current;
    const value = await api<ServiceStatus>("/api/service/status");
    if (g === generation.current) setStatus(value);
  };
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
          if (live) setNotice((e as Error).message);
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
        const [s, u] = await Promise.all([
          api<ServiceStatus>("/api/service/status"),
          api<Usage>("/api/me/usage"),
        ]);
        if (live && g === generation.current) {
          setStatus(s);
          setUsage(u);
        }
      } catch (e) {
        if (live) setNotice((e as Error).message);
      }
    };
    void load();
    const statusTimer = setInterval(
        () => void refreshStatus().catch((e) => live && setNotice(e.message)),
        2000,
      ),
      usageTimer = setInterval(() => void load(), 30000);
    const update = (event: Event) => setStatus((event as CustomEvent).detail);
    window.addEventListener("service-status", update);
    const stop = () => {
      live = false;
      generation.current++;
      clearInterval(statusTimer);
      clearInterval(usageTimer);
      window.removeEventListener("service-status", update);
    };
    window.addEventListener("pagehide", stop);
    return () => {
      stop();
      window.removeEventListener("pagehide", stop);
    };
  }, [ready, authenticated, publicMode, pollEpoch]);
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
