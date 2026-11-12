import { HStack } from "@astryxdesign/core/HStack";
import { Slider } from "@astryxdesign/core/Slider";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { NativeSelect } from "../../shared/ui/native-select";
import { Input } from "../../shared/ui/input";
import { Button } from "../../shared/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "../../shared/ui/dialog";
import { ArrowsOutIcon, CaretRightIcon, FunnelIcon, GraphIcon, ListBulletsIcon, MagnifyingGlassIcon } from "@phosphor-icons/react";
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
import { Markdown } from "../../shared/ui/UI";
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
  const projectDeleteOpener = useRef<HTMLButtonElement | null>(null);
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
          <h2 id="knowledge-title"><GraphIcon weight="duotone" size={26} aria-hidden />
            {admin ? "프로젝트 지식 그래프" : "결정과 명세 지식 그래프"}
          </h2>
          <p>저장된 결정, 근거와 명세의 관계를 살펴보세요.</p>
        </div>
      </header>
      {admin && (
        <HStack gap={2} wrap="wrap" className="project-bar">
          <div>
            프로젝트
            <NativeSelect
              aria-label="프로젝트" id="admin-project"
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
                  {p.name} (식별자 {p.id.slice(0, 8)})
                </option>
              ))}
            </NativeSelect>
          </div>
          <p id="project-notice" role="status">
            {project
              ? "프로젝트의 저장된 지식을 조회합니다."
              : "조회할 프로젝트를 선택하세요."}
          </p>
          <Button disabled={!project || busy} onClick={event => { projectDeleteOpener.current = event.currentTarget; void previewProject(); }}>
            빈 프로젝트 삭제 미리보기
          </Button>
        </HStack>
      )}
      <HStack gap={2} wrap="wrap" className="knowledge-controls">
        {!admin && session && <Button type="button" onClick={beginRequirement}>새 요구사항 영향 검토</Button>}
        <form
          id="knowledge-form"
          onSubmit={(e) => {
            e.preventDefault();
            void search();
          }}
        >
          <NativeSelect
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
                {s.request || "대화 세션"} (식별자 {s.id.slice(0, 8)})
              </option>
            ))}
          </NativeSelect>
          <Input
            id="knowledge-query"
            aria-label="검색"
            placeholder="지식 검색…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <Button type="submit" variant="default" disabled={busy}><MagnifyingGlassIcon size={18} aria-hidden />검색</Button>
        </form>
        <HStack gap={2} wrap="wrap" className="button-row">
          <Button
            id="graph-summary"
            aria-pressed={mode === "summary"}
            onClick={() => {
              setMode("summary");
              setExpanded(new Set());
            }}
          >
            요약
          </Button>
          <Button
            id="graph-detail-mode"
            aria-pressed={mode === "detail"}
            onClick={() => setMode("detail")}
          >
            상세
          </Button>
          <Button
            id="graph-list-toggle"
            aria-expanded={list}
            onClick={() => setList(!list)}
          >
            <ListBulletsIcon size={18} aria-hidden />목록
          </Button>
          <Button id="graph-fit" onClick={() => handle.current?.fit()}>
            <ArrowsOutIcon size={18} aria-hidden />전체 맞춤
          </Button>
        </HStack>
        <details className="graph-menu">
          <summary><CaretRightIcon className="graph-menu-caret" size={16} aria-hidden /><FunnelIcon size={16} aria-hidden /><span>필터</span></summary>
          <div>
            유형
            <NativeSelect
              aria-label="유형" id="knowledge-kind"
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
            </NativeSelect>
          </div>
          <div>
            상태
            <NativeSelect
              aria-label="상태" id="knowledge-status"
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
            </NativeSelect>
          </div>
        </details>
        <details className="graph-menu">
          <summary><CaretRightIcon className="graph-menu-caret" size={16} aria-hidden /><span>설정</span></summary>
          <Slider label="노드 간격" min={15} max={70} value={spacing} onChange={setSpacing} />
          <Slider label="연결 길이" min={50} max={200} value={distance} onChange={setDistance} />
          <Slider label="라벨 양" min={0} max={20} value={labels} onChange={setLabels} />
          <CheckboxInput label="배치 일시정지" value={paused} onChange={setPaused} />
          <Button id="graph-layout" onClick={() => handle.current?.layout()}>
            전체 재배치
          </Button>
        </details>
        {canRetry && (
          <Button
            id="knowledge-retry"
            disabled={busy || mutationBusy}
            onClick={() => void retryEmbeddings()}
          >
            임베딩 재시도
          </Button>
        )}
      </HStack>
      <div id="knowledge-notice" role="status" aria-live="polite">
        {notice || (busy ? "조회 중…" : <HStack gap={2} wrap="wrap" className="graph-counts">
          <span>화면 항목 <strong>{display.nodes.length}개</strong></span>
          <span>명세 묶음 <strong>{display.nodes.filter((n) => n.virtual).length}개</strong></span>
          <span>조회 항목 <strong>{display.rawCount}개</strong></span>
          <span>실제 관계 <strong>{display.rawEdges}개</strong></span>
          {results && <span>검색 결과 <strong>{results.length}개</strong></span>}
          {graph.has_more && <span>100개 제한으로 일부 표시</span>}
          {!!display.rawCount && !display.rawEdges && <span>현재 범위에 관계 없음</span>}
        </HStack>)}
      </div>
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
            aria-label="지식 항목과 검색 결과"
          >
            <header>
              <strong>지식 항목과 검색 결과</strong>
              <Button
                id="graph-list-close"
                aria-label="목록 닫기"
                onClick={() => setList(false)}
              >
                ×
              </Button>
            </header>
            <ul id="knowledge-nodes" aria-label="지식 항목 목록">
              {(results || graph.nodes).map((n) => (
                <li key={n.id}>
                  <Button onClick={() => void showNode(n.id)}>
                    <span className="graph-result-kind">{kinds[n.kind] || n.kind}</span><span>{n.body.slice(0, 90)}</span>
                  </Button>
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
              <Button
                id="graph-detail-close"
                aria-label="상세 닫기"
                onClick={clear}
              >
                ×
              </Button>
            </header>
            <div id="knowledge-detail">
              {newRequirement ? <ImpactReview key={`new:${session}`} jobId={session} inspect={id => void showNode(id)} /> : group ? (
                <>
                  <h3>{group.label}</h3>
                  <p>같은 작업·문서 버전의 명세를 묶어 표시합니다.</p>
                  <Button
                    onClick={() => {
                      setExpanded(
                        (previous) => new Set([...previous, group.id]),
                      );
                      setGroup(null);
                    }}
                  >
                    명세 묶음 펼치기
                  </Button>
                  <ul>
                    {group.members.map((id: string) => (
                      <li key={id}>
                        <Button onClick={() => void showNode(id)}>
                          {title(display.originals.get(id)!)}
                        </Button>
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                selected && (
                  <>
                    <h3 className="graph-detail-heading">
                      <span>{kinds[selected.kind]}</span><span>
                      {selected.active === false
                        ? "대체된 항목"
                        : (
                            {
                              confirmed: "사용자 확정",
                              proposed: "LLM 제안",
                              assumption: "가정",
                            } as Record<string, string>
                          )[selected.attrs?.status || ""] || "현재 항목"}</span>
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
                    {(selected.attrs?.sources?.length || 0) > 0 && (
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
                    <HStack gap={2} wrap="wrap" className="button-row">
                      <Button onClick={() => void expand(selected.id)}>
                        주변 관계 펼치기
                      </Button>
                      <Button onClick={() => void expand(selected.id, true)}>
                        이 항목 중심으로 보기
                      </Button>
                      <Button onClick={() => void expand(selected.id, true, 2)}>
                        2단계 주변 보기
                      </Button>
                    </HStack>
                    <ul>
                      {(selected.edges || [])
                        .filter(
                          (e) =>
                            e.source === selected.id ||
                            e.target === selected.id,
                        )
                        .map((e, i) => {
                          const other =
                            e.source === selected.id ? e.target : e.source;
                          return (
                            <li key={e.id || i}>
                              <Button onClick={() => void showNode(other)}>
                                {e.source === selected.id ? "→" : "←"}{" "}
                                <span className="graph-result-kind">{edgeLabels[e.kind] || e.kind}</span>{" "}
                                {(
                                  e.other_body ||
                                  display.originals.get(other)?.body ||
                                  "연결된 항목 열기"
                                ).slice(0, 70)}
                              </Button>
                            </li>
                          );
                        })}
                    </ul>
                    {selected.document !== undefined && (
                      <details>
                        <summary>이 버전의 명세 원문</summary>
                        <pre>{selected.document}</pre>
                        {selected.document_has_more && (
                          <Button
                            disabled={busy}
                            onClick={() => void documentMore()}
                          >
                            다음 내용 읽기
                          </Button>
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
              <i data-kind={k} aria-hidden style={{ background: colors[k] }} />
              {v}
            </span>
          ))}
        </div>
        <HStack gap={2} wrap="wrap" id="graph-relation" className="graph-hints" role="status">
          {relation ? <span>{relation}</span> : <><span>끌어서 이동</span><span>휠로 확대</span><span><kbd>Esc</kbd> 선택 해제</span></>}
        </HStack>
        <HStack gap={2} wrap="wrap" className="button-row">
          <Button
            id="graph-zoom-in"
            aria-label="그래프 확대"
            onClick={() => handle.current?.zoom(1.2)}
          >
            ＋
          </Button>
          <Button
            id="graph-zoom-out"
            aria-label="그래프 축소"
            onClick={() => handle.current?.zoom(1 / 1.2)}
          >
            −
          </Button>
          {focused && (
            <Button
              id="graph-back"
              onClick={() => {
                setMode("summary");
                setQuery("");
                setRefresh((r) => r + 1);
              }}
            >
              ← 전체 요약
            </Button>
          )}
          {display.orphans.length > 0 && (
            <Button id="graph-orphans" onClick={() => setOrphans(!orphans)}>
              {orphans ? "접기" : "펼치기"}: 이 범위에서 연결 없는 항목{" "}
              {display.orphans.length}개
            </Button>
          )}
        </HStack>
      </footer>
      {projectOperation && (
        <ProjectDelete
          operation={projectOperation}
          busy={busy}
          restoreFocus={() => {
            const target = projectDeleteOpener.current;
            if (target?.isConnected && !target.disabled) target.focus();
            else document.getElementById("admin-project")?.focus();
          }}
          onCancel={() => setProjectOperation(null)}
          onExecute={deleteProject}
        />
      )}
    </section>
  );
}
export function ProjectDelete({
  operation,
  busy,
  restoreFocus,
  onCancel,
  onExecute,
}: {
  operation: import("../admin/job-data").CleanupOperation & { project_id: string };
  busy: boolean;
  restoreFocus?: () => void;
  onCancel: () => void;
  onExecute: () => void;
}) {
  const opener = useRef(document.activeElement as HTMLElement | null);
  const cancel = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    // 2026-11-11: 삭제 확인은 취소를 우선하고 닫을 때 호출 위치를 복원한다.
    cancel.current?.focus();
    return () => {
      if (restoreFocus) restoreFocus();
      else if (opener.current?.isConnected) opener.current.focus();
    };
  }, []);
  return (
    <Dialog open onOpenChange={open => { if (!open && !busy) onCancel(); }}>
    <DialogContent id="cleanup-dialog" showCloseButton={false} onKeyDown={event => { if (busy && event.key === "Escape") event.preventDefault(); }}>
      <DialogTitle>빈 프로젝트 영구 삭제 확인</DialogTitle>
      <DialogDescription>
        작업이 없는 프로젝트를 삭제합니다. 삭제한 기록은 복구할 수 없습니다.
      </DialogDescription>
      <pre id="cleanup-summary">
        빈 프로젝트 1개 삭제{"\n"}
        {operation.project_id}
        {"\n"}
        {(operation.targets || []).join("\n")}
      </pre>
      <Button ref={cancel} id="cleanup-cancel" disabled={busy} autoFocus onClick={onCancel}>
        취소
      </Button>
      <Button id="cleanup-execute" variant="destructive" disabled={busy} onClick={onExecute}>
        영구 삭제
      </Button>
    </DialogContent>
    </Dialog>
  );
}
