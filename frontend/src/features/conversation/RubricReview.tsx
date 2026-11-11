import { Stack } from "@astryxdesign/core/Stack";
import { useState } from "react";
import { CaretDownIcon, CheckCircleIcon, WarningCircleIcon, QuestionIcon } from "@phosphor-icons/react";
import { Text } from "@astryxdesign/core/Text";
import { Button } from "../../shared/ui/UI";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../../shared/ui/collapsible";
import { Input } from "../../shared/ui/input";
import { NativeSelect, NativeSelectOption } from "../../shared/ui/native-select";
import { Pagination, PaginationContent, PaginationItem } from "../../shared/ui/pagination";
import type { RubricReview as Review } from "../../shared/types";
import "./rubric-review.css";

const labels = { PASS: "충족", FAIL: "미충족", UNDETERMINED: "판단 보류" } as const;
const importance = { core: "핵심", critical: "중요", secondary: "보조" } as const;
const severities: Record<string, string> = { blocking: "차단", major: "주요", minor: "경미" };
const sections: Record<string, string> = { acceptance_criteria: "인수 조건", test_plan: "테스트 계획", manual_verification_checklist: "수동 확인 절차", user_intent: "사용자 의도", in_scope: "포함 범위", data_flow: "데이터 흐름", input_contract: "입력 조건", configuration_policy: "설정 정책", error_handling_policy: "오류 처리 정책", module_responsibilities: "모듈 책임", architecture: "구조", mission: "목표", background: "배경" };
const labelReference = (name: string) => sections[name] || name;
type Filter = "all" | "attention" | "PASS" | "FAIL" | "UNDETERMINED";
const pageSize = 10;

function Verdict({ value }: { value: Review["items"][number]["verdict"] }) {
  const Icon = value === "PASS" ? CheckCircleIcon : value === "FAIL" ? WarningCircleIcon : QuestionIcon;
  return <Text type="supporting" className={`rubric-verdict rubric-verdict-${value.toLowerCase()}`}><Icon size={14} aria-hidden />{labels[value]}</Text>;
}

export function RubricReview({ review }: { review?: Review }) {
  // 2026-11-07: 평가가 바뀌면 이전 필터와 펼친 항목이 새 후보에 남지 않도록 상태를 분리한다.
  return review ? <ReviewContent key={review.evaluation_hash} review={review} /> : null;
}

function ReviewContent({ review }: { review: Review }) {
  const counts = { PASS: 0, FAIL: 0, UNDETERMINED: 0 };
  review.items.forEach(item => counts[item.verdict]++);
  const [filter, setFilter] = useState<Filter>(() => counts.FAIL || counts.UNDETERMINED ? "attention" : "all");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [descriptionOpen, setDescriptionOpen] = useState(false);
  const [listOpen, setListOpen] = useState(false);
  const stop = { max_score: "10점 도달", patience: "연속 비개선 한도 도달", round_budget: "평가 라운드 소진", "": "평가 진행 중" }[review.termination];
  const search = query.trim().toLocaleLowerCase();
  const filtered = review.items.filter(item => (filter === "all" || (filter === "attention" ? item.verdict !== "PASS" : item.verdict === filter)) &&
    (!search || [item.rubric_id, item.requirement_id, item.condition].some(text => text.toLocaleLowerCase().includes(search))));
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const displayedPage = Math.min(page, pages - 1);
  const resetPosition = () => { setPage(0); setExpanded(null); };
  return <section className="rubric-review" aria-label="명세 루브릭 평가">
    <header className="rubric-header"><h3>명세 평가 {review.score}/10</h3><Stack direction="horizontal" wrap="wrap" className="rubric-counts" aria-label="평가 판정 집계">
      <span>충족 {counts.PASS}</span><span>미충족 {counts.FAIL}</span><span>판단 보류 {counts.UNDETERMINED}</span>
    </Stack></header>
    <p className={`rubric-reason${descriptionOpen ? "" : " is-clamped"}`}>{review.score_reason}</p>
    <Collapsible open={descriptionOpen} onOpenChange={setDescriptionOpen}>
      <CollapsibleTrigger className="rubric-text-trigger">평가 설명 {descriptionOpen ? "접기" : "보기"}<CaretDownIcon size={14} aria-hidden /></CollapsibleTrigger>
      <CollapsibleContent><Stack direction="horizontal" wrap="wrap" className="rubric-meta magi-meta"><span>{stop}</span><span>평가 {review.round}회</span><span>최고점 후보: {review.selected_cycle}구간 {review.selected_round}회차</span></Stack></CollapsibleContent>
    </Collapsible>
    {!!review.remaining_issues.length && <Stack className="rubric-issues"><h4>남은 결함</h4><ul>{review.remaining_issues.map(issue => <li key={issue.issue_id}>
      <Stack direction="horizontal" wrap="wrap" className="rubric-issue-meta"><Text type="supporting">{severities[issue.severity] || issue.severity}</Text><span>{issue.issue_id}</span></Stack>
      <p><strong>문제</strong> {issue.problem}</p><p><strong>필요한 수정</strong> {issue.required_change}</p>
    </li>)}</ul></Stack>}
    {!!review.revision_directives.length && <Stack className="rubric-directives"><h4>수정 지시</h4><ul>{review.revision_directives.map((text, index) => <li key={index}>{text}</li>)}</ul></Stack>}
    <Collapsible open={listOpen} onOpenChange={setListOpen} className="rubric-list-section">
      <CollapsibleTrigger className="rubric-list-toggle">평가 항목 {review.items.length}개 {listOpen ? "접기" : "보기"}<CaretDownIcon size={15} aria-hidden /></CollapsibleTrigger>
      <CollapsibleContent><Stack direction="horizontal" wrap="wrap" className="rubric-filters">
        <Input type="search" aria-label="평가 항목 검색" placeholder="항목 번호, 요구사항 또는 조건 검색" value={query} onChange={event => { setQuery(event.target.value); resetPosition(); }} />
        <NativeSelect aria-label="평가 판정 필터" value={filter} onChange={event => { setFilter(event.target.value as Filter); resetPosition(); }}>
          <NativeSelectOption value="all">전체</NativeSelectOption><NativeSelectOption value="attention">확인 필요</NativeSelectOption><NativeSelectOption value="PASS">충족</NativeSelectOption><NativeSelectOption value="FAIL">미충족</NativeSelectOption><NativeSelectOption value="UNDETERMINED">판단 보류</NativeSelectOption>
        </NativeSelect>
      </Stack>
      {!filtered.length ? <p className="rubric-empty">{review.items.length ? "검색 조건에 맞는 평가 항목이 없습니다." : "표시할 평가 항목이 없습니다."}</p> : <>
        <ol className="rubric-list">{filtered.slice(displayedPage * pageSize, (displayedPage + 1) * pageSize).map(item => <li key={item.rubric_id}>
          <Collapsible open={expanded === item.rubric_id} onOpenChange={open => setExpanded(open ? item.rubric_id : null)}>
            <CollapsibleTrigger className="rubric-item-trigger" aria-label={`${labels[item.verdict]} ${item.rubric_id} ${item.requirement_id} ${item.condition}`}><span className="rubric-item-meta"><Verdict value={item.verdict} /><strong>{item.rubric_id}</strong><span>{item.requirement_id}</span></span><span className="rubric-condition">{item.condition}</span><CaretDownIcon size={16} aria-hidden /></CollapsibleTrigger>
            <CollapsibleContent className="rubric-detail">
              <p className="rubric-detail-meta magi-meta"><span>요구사항 {item.requirement_id}</span><span>{importance[item.importance]}</span></p>
              <section><h5>평가 조건</h5><p>{item.condition}</p></section>
              <section><h5>판정 사유</h5><p>{item.reason}</p></section>
              <section><h5>요구사항 근거</h5>{item.basis.length ? item.basis.map((basis, index) => <Stack className="rubric-quote" key={index}><span>{labelReference(basis.reference)}</span><blockquote>{basis.quote}</blockquote></Stack>) : <p>기록된 요구사항 근거가 없습니다.</p>}</section>
              <section><h5>명세 인용</h5><Stack className="rubric-quote"><span>{labelReference(item.section)}</span><blockquote>{item.evidence_kind === "absence" ? "해당 조건의 근거 없음" : item.quote}</blockquote></Stack></section>
            </CollapsibleContent>
          </Collapsible>
        </li>)}</ol>
        {pages > 1 && <Pagination aria-label="평가 항목 페이지"><PaginationContent><PaginationItem><Button disabled={displayedPage === 0} onClick={() => { setPage(displayedPage - 1); setExpanded(null); }}>이전</Button></PaginationItem><PaginationItem><span aria-live="polite">{displayedPage + 1} / {pages}</span></PaginationItem><PaginationItem><Button disabled={displayedPage + 1 === pages} onClick={() => { setPage(displayedPage + 1); setExpanded(null); }}>다음</Button></PaginationItem></PaginationContent></Pagination>}
      </>}
      </CollapsibleContent>
    </Collapsible>
  </section>;
}
