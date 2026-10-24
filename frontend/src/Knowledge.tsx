import { ArrowsOutIcon, FunnelIcon, GraphIcon, ListBulletsIcon, MagnifyingGlassIcon } from "@phosphor-icons/react";
import { useEffect, useRef } from "react";
import "./admin-knowledge.css";
import {
  colors,
  edgeLabels,
  kinds,
  title
} from "./graph-data";
import { ImpactReview } from "./ImpactReview";
import KnowledgeGraph from "./KnowledgeGraph";
import { Markdown } from "./UI";
import { useKnowledge } from "./useKnowledge";
const sourceLabel = (source: string) =>
  source.startsWith("user_request")
    ? "원래 요청"
    : source.startsWith("user_feedback")
      ? "수정 의견"
      : source.startsWith("user_answer:")
        ? "사용자 답변 " + source.split(":")[1]
        : source === "system"
          ? "시스템 규칙"
          : source;
export default function Knowledge({
  admin = false,
  onDeleted,
  selectedJobId,
}: {
  admin?: boolean;
  onDeleted?: (ids: string[]) => void;
  selectedJobId?: string;
}) {
  const {
    canRetry, mutationBusy, projects, project, setProject,
    sessions, session, setSession, query, setQuery,
    kind, setKind, status, setStatus, graph,
    results, matches, selected, group, setGroup,
    newRequirement, mode, setMode, setExpanded, orphans,
    setOrphans, list, setList, notice, busy,
    spacing, setSpacing, distance, setDistance, labels,
    setLabels, paused, setPaused, relation, setRelation,
    setRefresh, focused, projectOperation, setProjectOperation, handle,
    display, clear, search, expand, showNode,
    documentMore, previewProject, invalidate, beginRequirement, retryEmbeddings,
    deleteProject,
  } = useKnowledge({ admin, selectedJobId, onDeleted });
  return (
    <section
      className="knowledge-react"
      aria-labelledby="knowledge-title"
      onKeyDown={(e) => {
        if (e.key === "Escape" && !projectOperation) clear();
      }}
    >
      <header className="section-heading">
        <div>
          <span className="eyebrow">KNOWLEDGE</span>
          <h2 id="knowledge-title"><GraphIcon weight="duotone" size={26} aria-hidden />
            {admin ? "프로젝트 지식 그래프" : "결정과 명세 지식 그래프"}
          </h2>
          <p>저장된 결정, 근거와 명세의 관계를 살펴보세요.</p>
        </div>
      </header>
      {admin && (
        <div className="project-bar">
          <label>
            프로젝트
            <select
              id="admin-project"
              value={project}
              onChange={(e) => {
                invalidate();
                setProject(e.target.value);
                setSession("");
                setQuery("");
              }}
            >
              <option value="">프로젝트 선택</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} · {p.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          <p id="project-notice" role="status">
            {project
              ? "프로젝트의 저장된 지식을 조회합니다."
              : "조회할 프로젝트를 선택하세요."}
          </p>
          <button disabled={!project || busy} onClick={previewProject}>
            빈 프로젝트 삭제 미리보기
          </button>
        </div>
      )}
      <div className="knowledge-controls">
        {!admin && session && <button type="button" onClick={beginRequirement}>새 요구사항 영향 검토</button>}
        <form
          id="knowledge-form"
          onSubmit={(e) => {
            e.preventDefault();
            void search();
          }}
        >
          <select
            id="knowledge-session"
            aria-label="대화 세션"
            value={session}
            onChange={(e) => {
              invalidate();
              setSession(e.target.value);
            }}
          >
            <option value="">전체 세션</option>
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.request || "대화 세션"} · {s.id.slice(0, 8)}
              </option>
            ))}
          </select>
          <input
            id="knowledge-query"
            aria-label="검색"
            placeholder="지식 검색…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button disabled={busy}><MagnifyingGlassIcon size={18} aria-hidden />검색</button>
        </form>
        <div className="button-row">
          <button
            id="graph-summary"
            aria-pressed={mode === "summary"}
            onClick={() => {
              setMode("summary");
              setExpanded(new Set());
            }}
          >
            요약
          </button>
          <button
            id="graph-detail-mode"
            aria-pressed={mode === "detail"}
            onClick={() => setMode("detail")}
          >
            상세
          </button>
          <button
            id="graph-list-toggle"
            aria-expanded={list}
            onClick={() => setList(!list)}
          >
            <ListBulletsIcon size={18} aria-hidden />목록
          </button>
          <button id="graph-fit" onClick={() => handle.current?.fit()}>
            <ArrowsOutIcon size={18} aria-hidden />전체 맞춤
          </button>
        </div>
        <details className="graph-menu">
          <summary><FunnelIcon size={16} aria-hidden />필터</summary>
          <label>
            유형
            <select
              id="knowledge-kind"
              value={kind}
              onChange={(e) => {
                invalidate();
                setKind(e.target.value);
              }}
            >
              <option value="">전체 유형</option>
              {Object.entries(kinds).map(([v, t]) => (
                <option key={v} value={v}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label>
            상태
            <select
              id="knowledge-status"
              value={status}
              onChange={(e) => {
                invalidate();
                setStatus(e.target.value);
              }}
            >
              <option value="">현재 항목</option>
              <option value="confirmed">사용자 확정</option>
              <option value="proposed">LLM 제안</option>
              <option value="assumption">가정</option>
              <option value="superseded">대체된 항목</option>
            </select>
          </label>
        </details>
        <details className="graph-menu">
          <summary>설정</summary>
          <label>
            노드 간격
            <input
              id="graph-spacing"
              type="range"
              min="15"
              max="70"
              value={spacing}
              onChange={(e) => setSpacing(+e.target.value)}
            />
          </label>
          <label>
            연결 길이
            <input
              id="graph-distance"
              type="range"
              min="50"
              max="200"
              value={distance}
              onChange={(e) => setDistance(+e.target.value)}
            />
          </label>
          <label>
            라벨 양
            <input
              id="graph-label-amount"
              type="range"
              min="0"
              max="20"
              value={labels}
              onChange={(e) => setLabels(+e.target.value)}
            />
          </label>
          <label>
            <input
              id="graph-pause"
              type="checkbox"
              checked={paused}
              onChange={(e) => setPaused(e.target.checked)}
            />
            배치 일시정지
          </label>
          <button id="graph-layout" onClick={() => handle.current?.layout()}>
            전체 재배치
          </button>
        </details>
        {canRetry && (
          <button
            id="knowledge-retry"
            disabled={busy || mutationBusy}
            onClick={() => void retryEmbeddings()}
          >
            임베딩 재시도
          </button>
        )}
      </div>
      <p id="knowledge-notice" role="status" aria-live="polite">
        {notice ||
          (busy
            ? "조회 중…"
            : `화면 ${display.nodes.length}개 (명세 묶음 ${display.nodes.filter((n) => n.virtual).length}개) · 조회 항목 ${display.rawCount}개 · 실제 관계 ${display.rawEdges}개${graph.has_more ? " · 100개 제한으로 일부 표시" : ""}${display.rawCount && !display.rawEdges ? " · 현재 범위에 관계 없음" : ""}${results ? " · 검색 " + results.length + "개" : ""}`)}
      </p>
      <div className="react-graph-workspace">
        <KnowledgeGraph
          display={display}
          selected={selected?.id || ""}
          matches={matches}
          spacing={spacing}
          distance={distance}
          labels={labels}
          paused={paused}
          detail={mode === "detail"}
          onSelect={(n) => {
            if (n.virtual) {
              clear();
              setGroup(n);
            } else void showNode(n.id);
          }}
          onClear={clear}
          onRelation={setRelation}
          handle={handle}
        />
        {!display.nodes.length && !busy && (
          <p id="graph-empty" className="graph-empty">
            {graph.nodes.length
              ? "연결 없는 항목을 펼쳐보세요."
              : kind || status || query
                ? "현재 조회 조건에 맞는 항목이 없습니다."
                : "아직 저장된 지식이 없습니다."}
          </p>
        )}
        {list && (
          <aside
            id="knowledge-list"
            className="knowledge-drawer results-drawer"
            aria-label="지식 항목 · 검색 결과"
          >
            <header>
              <strong>지식 항목 · 검색 결과</strong>
              <button
                id="graph-list-close"
                aria-label="목록 닫기"
                onClick={() => setList(false)}
              >
                ×
              </button>
            </header>
            <ul id="knowledge-nodes" aria-label="지식 항목 목록">
              {(results || graph.nodes).map((n) => (
                <li key={n.id}>
                  <button onClick={() => void showNode(n.id)}>
                    {kinds[n.kind] || n.kind} · {n.body.slice(0, 90)}
                  </button>
                  {n.matches?.map((m, i) => (
                    <blockquote key={i}>{m.quote}</blockquote>
                  ))}
                </li>
              ))}
            </ul>
          </aside>
        )}
        {(selected || group || newRequirement) && (
          <aside
            id="graph-inspector"
            className="knowledge-drawer inspector-drawer"
            aria-label="선택한 지식 항목"
          >
            <header>
              <strong>선택 항목</strong>
              <button
                id="graph-detail-close"
                aria-label="상세 닫기"
                onClick={clear}
              >
                ×
              </button>
            </header>
            <div id="knowledge-detail">
              {newRequirement ? <ImpactReview key={`new:${session}`} jobId={session} inspect={id => void showNode(id)} /> : group ? (
                <>
                  <h3>{group.label}</h3>
                  <p>같은 작업·문서 버전의 명세를 묶어 표시합니다.</p>
                  <button
                    onClick={() => {
                      setExpanded(
                        (previous) => new Set([...previous, group.id]),
                      );
                      setGroup(null);
                    }}
                  >
                    명세 묶음 펼치기
                  </button>
                  <ul>
                    {group.members.map((id: string) => (
                      <li key={id}>
                        <button onClick={() => void showNode(id)}>
                          {title(display.originals.get(id)!)}
                        </button>
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                selected && (
                  <>
                    <h3>
                      {kinds[selected.kind]} ·{" "}
                      {selected.active === false
                        ? "대체된 항목"
                        : (
                            {
                              confirmed: "사용자 확정",
                              proposed: "LLM 제안",
                              assumption: "가정",
                            } as Record<string, string>
                          )[selected.attrs?.status] || "현재 항목"}
                    </h3>
                    {selected.attrs?.origin === "demo" && (
                      <p>데모 실행에서 가져온 자료입니다.</p>
                    )}
                    <p>
                      세션:{" "}
                      {sessions.find((s) => s.id === selected.job_id)
                        ?.request || selected.job_id}
                    </p>
                    <Markdown content={selected.body} />
                    {!admin && selected.kind === "requirement" && selected.job_id && <ImpactReview key={selected.id} jobId={selected.job_id} nodeId={selected.id} inspect={id => void showNode(id)} />}
                    {selected.attrs?.rationale && (
                      <p>명시된 근거: {selected.attrs.rationale}</p>
                    )}
                    {selected.attrs?.conditions && (
                      <p>적용 조건: {selected.attrs.conditions}</p>
                    )}
                    {selected.attrs?.sources?.length > 0 && (
                      <p>
                        출처:{" "}
                        {[
                          ...new Set(
                            (selected.attrs?.sources || []).map(sourceLabel),
                          ),
                        ].join(", ")}
                      </p>
                    )}
                    {selected.attrs?.original_text && (
                      <pre>{selected.attrs.original_text}</pre>
                    )}
                    <div className="button-row">
                      <button onClick={() => void expand(selected.id)}>
                        주변 관계 펼치기
                      </button>
                      <button onClick={() => void expand(selected.id, true)}>
                        이 항목 중심으로 보기
                      </button>
                      <button onClick={() => void expand(selected.id, true, 2)}>
                        2단계 주변 보기
                      </button>
                    </div>
                    <ul>
                      {(selected.edges || [])
                        .filter(
                          (e: any) =>
                            e.source === selected.id ||
                            e.target === selected.id,
                        )
                        .map((e: any, i: number) => {
                          const other =
                            e.source === selected.id ? e.target : e.source;
                          return (
                            <li key={e.id || i}>
                              <button onClick={() => void showNode(other)}>
                                {e.source === selected.id ? "→" : "←"}{" "}
                                {edgeLabels[e.kind] || e.kind} ·{" "}
                                {(
                                  e.other_body ||
                                  display.originals.get(other)?.body ||
                                  "연결된 항목 열기"
                                ).slice(0, 70)}
                              </button>
                            </li>
                          );
                        })}
                    </ul>
                    {selected.document !== undefined && (
                      <details>
                        <summary>이 버전의 명세 원문</summary>
                        <pre>{selected.document}</pre>
                        {selected.document_has_more && (
                          <button
                            disabled={busy}
                            onClick={() => void documentMore()}
                          >
                            다음 내용 읽기
                          </button>
                        )}
                      </details>
                    )}
                  </>
                )
              )}
            </div>
          </aside>
        )}
      </div>
      <footer className="graph-footer">
        <div id="graph-legend">
          {Object.entries(kinds).map(([k, v]) => (
            <span key={k}>
              <i style={{ background: colors[k] }} />
              {v}
            </span>
          ))}
        </div>
        <p id="graph-relation" role="status">
          {relation}
        </p>
        <div className="button-row">
          <button
            id="graph-zoom-in"
            aria-label="그래프 확대"
            onClick={() => handle.current?.zoom(1.2)}
          >
            ＋
          </button>
          <button
            id="graph-zoom-out"
            aria-label="그래프 축소"
            onClick={() => handle.current?.zoom(1 / 1.2)}
          >
            −
          </button>
          {focused && (
            <button
              id="graph-back"
              onClick={() => {
                setMode("summary");
                setQuery("");
                setRefresh((r) => r + 1);
              }}
            >
              ← 전체 요약
            </button>
          )}
          {display.orphans.length > 0 && (
            <button id="graph-orphans" onClick={() => setOrphans(!orphans)}>
              {orphans ? "접기" : "펼치기"}: 이 범위에서 연결 없는 항목{" "}
              {display.orphans.length}개
            </button>
          )}
        </div>
      </footer>
      {projectOperation && (
        <ProjectDelete
          operation={projectOperation}
          busy={busy}
          onCancel={() => setProjectOperation(null)}
          onExecute={deleteProject}
        />
      )}
    </section>
  );
}
function ProjectDelete({
  operation,
  busy,
  onCancel,
  onExecute,
}: {
  operation: any;
  busy: boolean;
  onCancel: () => void;
  onExecute: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    ref.current?.showModal();
    return () => {
      if (opener?.isConnected) opener.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      id="cleanup-dialog"
      onCancel={(e) => {
        if (busy) e.preventDefault();
        else onCancel();
      }}
    >
      <h2>빈 프로젝트 영구 삭제 확인</h2>
      <p>
        작업이 없는 프로젝트를 삭제합니다. 삭제한 기록은 복구할 수 없습니다.
      </p>
      <pre id="cleanup-summary">
        빈 프로젝트 1개 삭제{"\n"}
        {operation.project_id}
        {"\n"}
        {(operation.targets || []).join("\n")}
      </pre>
      <button id="cleanup-cancel" disabled={busy} autoFocus onClick={onCancel}>
        취소
      </button>
      <button id="cleanup-execute" disabled={busy} onClick={onExecute}>
        영구 삭제
      </button>
    </dialog>
  );
}
