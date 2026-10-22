import { Button as ShadcnButton } from "./components/ui/button";
import { InfoIcon } from "@phosphor-icons/react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkParse from "remark-parse";
import { unified } from "unified";
import { useId, useMemo } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
export function Button({
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <ShadcnButton type="button" variant={className.split(" ").includes("primary") ? "default" : "outline"} className={`button ${className}`} {...props} />;
}
export function Notice({ children }: { children?: ReactNode }) {
  return children ? (
    <div className="notice" role="status">
      <InfoIcon weight="duotone" size={20} aria-hidden />{children}
    </div>
  ) : null;
}
const markdownParser = unified().use(remarkParse).use(remarkGfm);
type MarkdownNode = {
  type: string;
  depth?: number;
  value?: string;
  alt?: string | null;
  children?: MarkdownNode[];
  position?: { start: { line: number } };
};
function headingText(node: MarkdownNode): string {
  if (node.type === "text" || node.type === "inlineCode")
    return node.value || "";
  if (node.type === "image" || node.type === "imageReference")
    return node.alt || "";
  return node.children?.map(headingText).join("") || "";
}
export function Markdown({ content }: { content: string }) {
  const instanceId = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const headingId = (line?: number) => `document-${instanceId}-heading-${line}`;
  const headings = useMemo(() => {
    const result: { line: number; text: string }[] = [];
    function visit(node: MarkdownNode) {
      if (
        node.type === "heading" &&
        (node.depth === 2 || node.depth === 3) &&
        node.position
      ) {
        result.push({
          line: node.position.start.line,
          text: headingText(node),
        });
      }
      node.children?.forEach(visit);
    }
    // 렌더러와 같은 Markdown 구문으로 코드 예제를 제외하고 중첩 제목까지 수집한다.
    visit(markdownParser.parse(content));
    return result;
  }, [content]);
  return (
    <article className="markdown-view">
      {headings.length > 0 && (
        <details className="document-toc">
          <summary>문서 목차</summary>
          {headings.map((heading) => (
            <a key={heading.line} href={`#${headingId(heading.line)}`}>
              {heading.text}
            </a>
          ))}
        </details>
      )}
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        urlTransform={defaultUrlTransform}
        components={{
          h2: ({ children, node }) => (
            <h2 id={headingId(node?.position?.start.line)}>{children}</h2>
          ),
          h3: ({ children, node }) => (
            <h3 id={headingId(node?.position?.start.line)}>{children}</h3>
          ),
          a: ({ children, ...props }) => (
            <a {...props} rel="noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </article>
  );
}
export const statusLabel = (status?: string) =>
  ({
    queued: "대기 중",
    running: "실행 중",
    completed: "완료",
    waiting: "답변 필요",
    waiting_approval: "승인 대기",
    needs_revision: "보완 필요",
    blocked: "명세 보완 실패",
    failed: "오류",
    interrupted: "중단됨",
    NEEDS_USER_INPUT: "요구사항 확인 필요",
    PASS_PENDING_USER_APPROVAL: "명세 문서 검토 통과 · 사용자 승인 대기",
    CRITICAL_BLOCKED: "명세 보완 실패",
    FINALIZED: "최종 완료",
    error: "오류",
  })[status || ""] ||
  status ||
  "기록 없음";
export const formatTime = (value?: string) =>
  value && !Number.isNaN(new Date(value).valueOf())
    ? new Date(value).toLocaleString("ko-KR")
    : "기록 없음";

export function usageLabel(usage?: Record<string, any>) {
  if (!usage) return "사용량: 아직 기록되지 않았습니다.";
  const token = (value: unknown) =>
    typeof value === "number" && Number.isInteger(value)
      ? value.toLocaleString("ko-KR")
      : "알 수 없음";
  const coverage = (name: string) =>
    Number.isInteger(usage[name]?.known_calls) &&
    Number.isInteger(usage.successful_calls)
      ? ` (${usage[name].known_calls}/${usage.successful_calls}개 알려짐)`
      : "";
  const cache = usage.cache_rate?.value;
  return `제공자 호출 ${token(usage.calls)}회 · 입력 ${token(usage.input_tokens)}${coverage("input_token_coverage")} · 출력 ${token(usage.output_tokens)}${coverage("output_token_coverage")} · OpenAI 캐시 ${token(usage.cached_tokens)} · 적중률 ${typeof cache === "number" ? (cache * 100).toFixed(1) + "%" : "알 수 없음"}${usage.recording_incomplete ? " · 일부 기록 누락" : ""}`;
}
