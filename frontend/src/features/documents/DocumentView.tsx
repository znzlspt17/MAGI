import { Stack } from "@astryxdesign/core/Stack";
import { DownloadSimpleIcon } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import { Button, Markdown } from "../../shared/ui/UI";
import type { DocumentData } from "../../shared/types";
import { RequirementReview, type RequirementEvidence } from "../requirements/RequirementReview";
import { ApprovedDecisions } from "../projects/ProjectDecisions";
import { ImplementationPackage } from "./ImplementationPackage";

export function DocumentView({
  jobId,
  stepId,
  document,
  onQuestion,
  reviewOnly = false,
  onShowDocument,
}: {
  jobId: string;
  stepId: string;
  document: DocumentData;
  onQuestion?: (question: string) => void;
  reviewOnly?: boolean;
  onShowDocument?: () => void;
}) {
  const [mode, setMode] = useState("rendered");
  const [location, setLocation] = useState<RequirementEvidence | null>(null);
  const original = useRef<HTMLPreElement>(null);
  const source = document.content, hash = document.source_hash;
  const normalized = source.replace(/\r\n?/g, "\n").trimEnd();
  useEffect(() => { setLocation(null); }, [jobId, stepId, source]);
  function locate(ref: RequirementEvidence) {
    // 2026-11-04: 서버가 기록한 코드 포인트 위치를 사용해 이모지 뒤의 인용도 정확히 찾는다.
    if (Array.from(normalized).slice(ref.start, ref.end).join("") !== ref.quote) return;
    setLocation(ref); setMode("raw");
    onShowDocument?.();
  }
  useEffect(() => {
    if (location && !reviewOnly) {
      original.current?.querySelector("mark")?.scrollIntoView?.({ block: "center" });
      original.current?.focus();
    }
  }, [location, reviewOnly]);
  function download() {
    const url = URL.createObjectURL(
      new Blob([source], { type: "text/markdown;charset=utf-8" }),
    );
    const a = window.document.createElement("a");
    a.href = url;
    a.download = document.filename || "SPEC.ko.md";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
  return (
    <section aria-label="명세 문서">
      {document.kind === "final" && document.completed_id && <ApprovedDecisions key={`decisions:${jobId}:${document.completed_id}`} jobId={jobId} completedId={document.completed_id} />}
      {document.kind === "final" && document.completed_id && <ImplementationPackage key={`${jobId}:${document.completed_id}`} jobId={jobId} completedId={document.completed_id} />}
      {["candidate", "final"].includes(document.kind || "") && (reviewOnly
        ? <RequirementReview key={`${jobId}:${stepId}:${hash || source}`} jobId={jobId} stepId={stepId} sourceHash={hash} onLocate={locate} onQuestion={onQuestion} />
        : <details className="document-review" key={`${jobId}:${stepId}:${hash || source}`}><summary>요구사항별 검토 근거</summary><RequirementReview jobId={jobId} stepId={stepId} sourceHash={hash} onLocate={locate} onQuestion={onQuestion} /></details>)}
      {reviewOnly ? <Button onClick={onShowDocument}>명세 문서 보기</Button> : <>
      <Stack direction="horizontal" wrap="wrap" className="document-controls">
        {[["rendered", "문서 보기"], ["raw", "Markdown 보기"]].map(([value, label]) => (
          <Button key={value} aria-pressed={mode === value} onClick={() => setMode(value)}>{label}</Button>
        ))}
        <Button onClick={download}><DownloadSimpleIcon size={18} aria-hidden />Markdown 다운로드</Button>
      </Stack>
      <p className="subtle">한국어 명세 원문이 다운로드됩니다.</p>
      {mode === "raw" ? (
        location ? <pre ref={original} tabIndex={-1} aria-label="선택한 근거의 명세 원문" className="rr-original">{Array.from(normalized).slice(0, location.start).join("")}<mark>{Array.from(normalized).slice(location.start, location.end).join("")}</mark>{Array.from(normalized).slice(location.end).join("")}</pre> : <pre className="markdown-raw">{source}</pre>
      ) : <Markdown content={source} />}
      </>}
    </section>
  );
}
