import { DownloadSimpleIcon } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import { post } from "./api";
import { Button, Markdown, Notice } from "./UI";
import type { DocumentData } from "./types";
import { RequirementReview, type RequirementEvidence } from "./RequirementReview";
import { ApprovedDecisions } from "./ProjectDecisions";
import { ImplementationPackage } from "./ImplementationPackage";
export function DocumentView({
  jobId,
  stepId,
  document,
  onQuestion,
  reviewOnly = false,
  onShowDocument,
  initialLanguage = "ko",
}: {
  initialLanguage?: "ko" | "en";
  jobId: string;
  stepId: string;
  document: DocumentData;
  onQuestion?: (question: string) => void;
  reviewOnly?: boolean;
  onShowDocument?: () => void;
}) {
  const [language, setLanguage] = useState<string>(initialLanguage),
    [mode, setMode] = useState("rendered"),
    [retry, setRetry] = useState(0),
    [active, setActive] = useState<DocumentData | null>(null),
    [error, setError] = useState("");
  const sequence = useRef(0),
    cache = useRef(new Map<string, DocumentData>()),
    pending = useRef(new Map<string, Promise<DocumentData>>()),
    controllers = useRef(new Set<AbortController>());
  const [location, setLocation] = useState<RequirementEvidence | null>(null);
  const original = useRef<HTMLPreElement>(null);
  const normalized = document.content.replace(/\r\n?/g, "\n").trimEnd();
  useEffect(() => { setLocation(null); }, [jobId, stepId, document.content]);
  function locate(ref: RequirementEvidence) {
    if (Array.from(normalized).slice(ref.start, ref.end).join("") !== ref.quote) return;
    setLocation(ref); setLanguage("en"); setMode("raw");
    onShowDocument?.();
  }
  useEffect(() => {
    if (location) { original.current?.querySelector("mark")?.scrollIntoView?.({ block: "center" }); original.current?.focus(); }
  }, [location, active]);
  const source = document.content,
    hash = document.source_hash;
  useEffect(
    () => () => {
      controllers.current.forEach((controller) => controller.abort());
      controllers.current.clear();
      pending.current.clear();
    },
    [jobId, stepId, source, hash],
  );
  useEffect(() => {
    const current = ++sequence.current;
    setActive(null);
    setError("");
    if (reviewOnly) return;
    const key = `${jobId}:${stepId}:${hash || source}:${language}`;
    if (language === "en") {
      setActive({ ...document, language: "en" });
      return () => {
        sequence.current++;
      };
    }
    const saved = cache.current.get(key);
    if (saved) {
      setActive(saved);
      return () => {
        sequence.current++;
      };
    }
    if (!pending.current.has(key)) {
      const controller = new AbortController();
      controllers.current.add(controller);
      const task = post<DocumentData>(
        `/api/jobs/${encodeURIComponent(jobId)}/steps/${encodeURIComponent(stepId)}/document`,
        { language: "ko" },
        { signal: controller.signal },
      )
        .then((value) => {
          if (controller.signal.aborted)
            throw new DOMException("취소됨", "AbortError");
          if (typeof value.content !== "string" || value.language !== "ko")
            throw new Error("한국어 번역본을 확인할 수 없습니다.");
          if (hash && value.source_hash !== hash)
            throw new Error(
              "원문이 변경되었습니다. 해당 단계를 다시 열어주세요.",
            );
          cache.current.set(key, value);
          return value;
        })
        .finally(() => {
          controllers.current.delete(controller);
          if (pending.current.get(key) === task) pending.current.delete(key);
        });
      pending.current.set(key, task);
    }
    pending.current
      .get(key)!
      .then((value) => {
        if (current === sequence.current) setActive(value);
      })
      .catch((e) => {
        if (current === sequence.current && e.name !== "AbortError")
          setError(e.message);
      });
    return () => {
      sequence.current++;
    };
  }, [jobId, stepId, source, hash, language, retry, reviewOnly]);
  function download() {
    if (!active) return;
    const url = URL.createObjectURL(
      new Blob([active.content], { type: "text/markdown;charset=utf-8" }),
    );
    const a = window.document.createElement("a");
    a.href = url;
    a.download = active.filename || `SPEC.${language}.md`;
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
      <div className="document-controls">
        {[
          ["ko", "한국어"],
          ["en", "English"],
        ].map(([lang, label]) => (
          <Button
            key={lang}
            aria-pressed={language === lang}
            onClick={() => setLanguage(lang)}
          >
            {label}
          </Button>
        ))}
        <span className="control-divider" />
        {[
          ["rendered", "문서 보기"],
          ["raw", "Markdown 보기"],
        ].map(([value, label]) => (
          <Button
            key={value}
            aria-pressed={mode === value}
            onClick={() => setMode(value)}
          >
            {label}
          </Button>
        ))}
        <Button disabled={!active} onClick={download}>
          <DownloadSimpleIcon size={18} aria-hidden />Markdown 다운로드
        </Button>
      </div>
      <p className="subtle" role="status">
        {active
          ? language === "ko"
            ? "한국어 번역본 · 현재 보이는 한국어본이 다운로드됩니다."
            : "영어 원문 · 현재 보이는 영어본이 다운로드됩니다."
          : error
            ? ""
            : "한국어본을 준비하고 있습니다. 처음 열 때 번역본을 생성하며, 이후에는 저장된 번역본을 사용합니다."}
      </p>
      {error && (
        <>
          <Notice>
            한국어본을 준비하지 못했습니다. {error} 영어 원문은 English에서
            확인할 수 있습니다.
          </Notice>
          <Button onClick={() => setRetry((v) => v + 1)}>
            한국어본 다시 생성
          </Button>
        </>
      )}
      {active &&
        (mode === "raw" ? (
          location && language === "en" ? <pre ref={original} tabIndex={-1} aria-label="선택한 근거의 영어 명세 원문" className="rr-original">{Array.from(normalized).slice(0, location.start).join("")}<mark>{Array.from(normalized).slice(location.start, location.end).join("")}</mark>{Array.from(normalized).slice(location.end).join("")}</pre> : <pre className="markdown-raw">{active.content}</pre>
        ) : (
          <Markdown content={active.content} />
        ))}
      </>}
    </section>
  );
}
