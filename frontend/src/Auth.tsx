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
      const prefix = `magi:draft:${currentUser.current.id}`;
      Object.keys(sessionStorage)
        .filter((key) => key === prefix || key.startsWith(prefix + ":"))
        .forEach((key) => sessionStorage.removeItem(key));
    }
    configureAuth({ publicMode: true });
    clearRequests();
    setUser(null);
    setUsage(null);
    setStatus({});
    if (/^\/jobs\/[0-9a-f]{32}$/.test(location.pathname))
      sessionStorage.setItem("magi:return-path", location.pathname);
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
          const path = sessionStorage.getItem("magi:return-path");
          if (
            location.pathname === "/" &&
            /^\/jobs\/[0-9a-f]{32}$/.test(path || "")
          )
            location.replace(path!);
          sessionStorage.removeItem("magi:return-path");
        } catch (e) {
          if (live) setNotice((e as Error).message);
        }
      } catch (e) {
        if (live) setNotice((e as Error).message);
      } finally {
        if (live) setReady(true);
      }
    })();
    window.addEventListener("magi:signed-out", signedOut);
    return () => {
      live = false;
      generation.current++;
      window.removeEventListener("magi:signed-out", signedOut);
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
    window.addEventListener("magi:service-status", update);
    const stop = () => {
      live = false;
      generation.current++;
      clearInterval(statusTimer);
      clearInterval(usageTimer);
      window.removeEventListener("magi:service-status", update);
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
  if (!authenticated)
    return (
      <main className="login">
        <span className="eyebrow">MAGI WORKSPACE</span>
        <h1>
          개발 요청을
          <br />
          검토 가능한 명세로
        </h1>
        <p>요청 작성 → 요구사항 확인 → 명세 검토 → 승인과 다운로드</p>
        <p>
          이름·이메일·사진은 요청하지 않습니다. 계정 구분용 식별 정보만
          사용합니다.
        </p>
        <p role="status">
          {notice ||
            (loginAvailable
              ? "Google 계정으로 로그인하세요."
              : "Google 로그인 설정이 준비되지 않았습니다. 운영자에게 문의하세요.")}
        </p>
        {loginAvailable && (
          <a className="button primary" href="/auth/google/start">
            Google로 로그인
          </a>
        )}
        <a href="/privacy">정보 처리 안내</a>
      </main>
    );
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
