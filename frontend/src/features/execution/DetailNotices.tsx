import { Notice } from "../../shared/ui/UI";
import type { StepDetail } from "./execution-detail";

// 2026-11-05: 같은 단계 상세를 보여주는 대화와 이력에서 누락 원인을 같은 방식으로 구분한다.
export function DetailNotices({ detail }: { detail: Pick<StepDetail, "recording_incomplete" | "response_incomplete"> }) {
  return <>
    {detail.recording_incomplete && <Notice>일부 상세 기록이 누락되었습니다. 표시 가능한 결과만 제공합니다.</Notice>}
    {detail.response_incomplete && <Notice>일부 응답을 해석하지 못했습니다. 확인 가능한 결과만 표시합니다.</Notice>}
  </>;
}
