import { Banner } from "@astryxdesign/core/Banner";
import { ClockIcon, CheckCircleIcon, WarningCircleIcon } from "@phosphor-icons/react";
import { useAuth } from "../auth/Auth";
import type { ServiceStatus } from "../../shared/types";

export function serviceState(publicMode: boolean, status: ServiceStatus) {
  if (!publicMode) return { kind: "available", title: "MAGI를 사용할 수 있습니다", description: "", blocked: false };
  if (status.checkState === "error") return { kind: "unknown", title: "서비스 연결을 확인해주세요", description: "잠시 후 다시 시도해주세요.", blocked: true };
  if (status.checkState === "loading" || status.ready !== true) return { kind: "unknown", title: "서비스 상태를 확인 중입니다", description: "요청은 미리 작성할 수 있습니다.", blocked: true };
  return { kind: "available", title: "MAGI를 사용할 수 있습니다", description: "", blocked: false };
}

export function ServiceStatusNotice({ inline = false, compact = false }: { inline?: boolean; compact?: boolean }) {
  const auth = useAuth();
  const state = serviceState(auth.publicMode, auth.status);
  if (inline && !state.blocked) return null;
  const Icon = state.kind === "available" ? CheckCircleIcon : state.kind === "unknown" ? WarningCircleIcon : ClockIcon;
  const counts = auth.publicMode && state.kind === "available" ? `실행 ${auth.status.active_count || 0}/${auth.status.max_parallel || 2} 대기 ${auth.status.queued_count || 0}` : "";
  if (compact && !state.blocked) return <span className="service-status-compact" role="status" aria-label={`${state.title} ${counts}`} title={`${state.title} ${counts}`}><Icon size={16} aria-hidden /></span>;
  return <Banner className={`service-status-banner ${state.kind} ${inline ? "inline" : ""}`} status={state.blocked ? "warning" : "success"}
    role={inline ? undefined : "status"} aria-live={inline ? undefined : "polite"} aria-atomic={inline ? undefined : true}
    icon={<Icon size={22} aria-hidden />} title={state.title} description={<>{state.description}{counts && <span> {counts}</span>}</>} />;
}
