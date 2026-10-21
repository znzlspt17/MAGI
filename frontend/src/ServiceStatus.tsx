import { ClockIcon, CheckCircleIcon, WarningCircleIcon } from "@phosphor-icons/react";
import { useAuth } from "./Auth";
import type { ServiceStatus } from "./types";

export function serviceState(publicMode: boolean, status: ServiceStatus) {
  if (!publicMode) return { kind: "available", title: "로컬 작업 공간", description: "", blocked: false };
  if (status.checkState === "error") return { kind: "unknown", title: "사용 가능 상태를 확인할 수 없습니다", description: "연결을 확인하고 있습니다. 작성 중인 내용은 유지됩니다.", blocked: true };
  if (status.checkState === "loading" || typeof status.busy !== "boolean" || (status.busy && typeof status.mine !== "boolean")) return { kind: "unknown", title: "사용 가능 상태를 확인 중입니다", description: "잠시만 기다려 주세요. 요청은 미리 작성할 수 있습니다.", blocked: true };
  if (status.recovering || status.phase === "recovery") return { kind: "waiting", title: "서비스 복구 확인 중입니다", description: "내 기록은 계속 볼 수 있습니다.", blocked: true };
  if (!status.busy) return { kind: "available", title: "MAGI를 사용할 수 있습니다", description: "", blocked: false };
  if (!status.mine) return { kind: "waiting", title: "다른 사용자가 이용 중입니다", description: "새 요청은 잠시 후 가능합니다. 내 기록은 계속 볼 수 있습니다.", blocked: true };
  return { kind: "owned", title: status.phase === "waiting" ? "내 답변을 기다리고 있습니다" : "내 요청을 처리 중입니다", description: "", blocked: false };
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
