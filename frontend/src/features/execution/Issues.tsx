import type { IssueData, StepResultData } from "./execution-detail";

export function Issues({ result, open = false }: { result: StepResultData; open?: boolean }) {
  const render = (items: IssueData[], resolved = false) =>
    items.map((issue, i) => (
      <article className="issue-card" key={i}>
        <small>
          {resolved
            ? "해소됨"
            : issue.lifecycle === "persistent"
              ? "계속 남음"
              : "새 지적"}{" "}
          · {issue.severity}
        </small>
        <h4>{issue.problem || issue.title || "검토 항목"}</h4>
        {([
          ["requirement_id", "요구사항"],
          ["section", "섹션"],
          ["defect_kind", "결함 유형"],
          ["resolution_reason", "해결 판단"],
          ["resolution_kind", "처리 분류"],
          ["decision_answer_id", "재사용한 답변"],
          ["missing_information", "미확정 내용"],
          ["decision_key", "결정 주제"],
          ["required_change", "필요한 수정"],
        ] as const).map(([key, label]) =>
          issue[key] ? (
            <p key={key}>
              <strong>{label}: </strong>
              {issue[key]}
            </p>
          ) : null,
        )}
        {!!issue.basis_refs?.length && <p><strong>확정 근거: </strong>{issue.basis_refs.join(", ")}</p>}
        {(Array.isArray(issue.evidence)
          ? issue.evidence
          : issue.evidence
            ? [issue.evidence]
            : []
        ).map((e, n) => (
          <blockquote key={n}>
            {typeof e === "string" ? e : `${e.source || ""} · ${e.quote || ""}`}
          </blockquote>
        ))}
      </article>
    ));
  return (
    <details className="issues" open={open || undefined}>
      <summary>검토 항목 · {result.issues?.length || 0}건</summary>
      {render(result.issues || [])}
      {!!result.resolved_issues?.length && (
        <details>
          <summary>
            다음 검토에서 해소됨 · {result.resolved_issues.length}건
          </summary>
          {render(result.resolved_issues, true)}
        </details>
      )}
      {result.report && (
        <details>
          <summary>원본 검토 보고서 보기</summary>
          <pre>{result.report}</pre>
        </details>
      )}
    </details>
  );
}
