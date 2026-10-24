import { ClockIcon, CheckCircleIcon, WarningCircleIcon } from "@phosphor-icons/react";
import { useAuth } from "./Auth";
import type { ServiceStatus } from "./types";

export function serviceState(publicMode: boolean, status: ServiceStatus) {
  if (!publicMode) return { kind: "available", title: "MAGI를 사용할 수 있습니다", description: "", blocked: false };
  if (status.checkState === "error") return { kind: "unknown", title: "서비스 연결을 확인해주세요", description: "잠시 후 다시 시도해주세요.", blocked: true };
  if (status.checkState === "loading" || status.ready !== true) return { kind: "unknown", title: "서비스 상태를 확인 중입니다", description: "요청은 미리 작성할 수 있습니다.", blocked: true };
  return { kind: "available", title: "MAGI를 사용할 수 있습니다", description: `실행 ${status.active_count || 0}/${status.max_parallel || 2} · 대기 ${status.queued_count || 0}`, blocked: false };
}

export function ServiceStatusNotice({ inline = false }: { inline?: boolean }) {
  const auth = useAuth();
  const state = serviceState(auth.publicMode, auth.status);
  if (inline && !state.blocked) return null;
  const Icon = state.kind === "available" ? CheckCircleIcon : state.kind === "unknown" ? WarningCircleIcon : ClockIcon;
  return <div className={`service-status-banner ${state.kind} ${inline ? "inline" : ""}`} role={inline ? undefined : "status"} aria-live={inline ? undefined : "polite"} aria-atomic={inline ? undefined : true}>
    <Icon size={22} aria-hidden /><div><strong>{state.title}</strong>{state.description && <p>{state.description}</p>}</div>
  </div>;
}
