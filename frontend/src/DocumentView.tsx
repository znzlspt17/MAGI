import { DownloadSimpleIcon } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import { post } from "./api";
import { Button, Markdown, Notice } from "./UI";
import type { DocumentData } from "./types";
export function DocumentView({
  jobId,
  stepId,
  document,
}: {
  jobId: string;
  stepId: string;
  document: DocumentData;
}) {
  const [language, setLanguage] = useState("ko"),
    [mode, setMode] = useState("rendered"),
    [retry, setRetry] = useState(0),
    [active, setActive] = useState<DocumentData | null>(null),
    [error, setError] = useState("");
  const sequence = useRef(0),
    cache = useRef(new Map<string, DocumentData>()),
    pending = useRef(new Map<string, Promise<DocumentData>>()),
    controllers = useRef(new Set<AbortController>());
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
  }, [jobId, stepId, source, hash, language, retry]);
  function download() {
    if (!active) return;
    const url = URL.createObjectURL(
      new Blob([active.content], { type: "text/markdown;charset=utf-8" }),
    );
    const a = window.document.createElement("a");
    a.href = url;
    a.download = active.filename || `MAGI_SPEC.${language}.md`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
  return (
    <section aria-label="명세 문서">
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
          <pre className="markdown-raw">{active.content}</pre>
        ) : (
          <Markdown content={active.content} />
        ))}
    </section>
  );
}
