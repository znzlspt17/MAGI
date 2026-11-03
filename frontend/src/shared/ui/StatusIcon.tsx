import { CheckCircleIcon, CircleNotchIcon, ClockIcon, QuestionIcon, StopCircleIcon, WarningCircleIcon } from "@phosphor-icons/react";
import { statusLabel } from "./UI";

// 색상이나 움직임 없이도 상태를 구분할 수 있도록 서로 다른 형태를 사용한다.
export function StatusIcon({ status, size = 16 }: { status?: string; size?: number }) {
  const Icon = status === "running" ? CircleNotchIcon
    : ["completed", "FINALIZED"].includes(status || "") ? CheckCircleIcon
    : ["waiting", "NEEDS_USER_INPUT", "PASS_PENDING_USER_APPROVAL"].includes(status || "") ? QuestionIcon
    : ["interrupted", "CRITICAL_BLOCKED", "blocked"].includes(status || "") ? StopCircleIcon
    : ["error", "failed"].includes(status || "") ? WarningCircleIcon : ClockIcon;
  return <span className={`status-icon${status === "running" ? " is-running" : ""}`} role="img" aria-label={statusLabel(status)} title={statusLabel(status)} data-status={status}><Icon size={size} aria-hidden /></span>;
}
