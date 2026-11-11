import { VStack } from "@astryxdesign/core/VStack";
import { HStack } from "@astryxdesign/core/HStack";
import { Table, TableHeader, TableBody, TableRow, TableHeaderCell, TableCell } from "@astryxdesign/core/Table";
import { Field } from "@astryxdesign/core/Field";
import { NativeSelect } from "../../shared/ui/native-select";
import { Input } from "../../shared/ui/input";
import { decodeUsageRows, decodeUsageSummary } from "./admin-response";
// shadcn/ui dashboard-01의 요약 카드·차트·데이터 표 구성을 MAGI에 맞게 적용한다(MIT).
// https://github.com/shadcn-ui/ui/tree/ba1503c64472b82256d9de95e2e62c5901a38e8b
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowsClockwiseIcon, ArrowRightIcon, CalendarBlankIcon, ChartBarIcon, CheckCircleIcon, CoinsIcon, CopyIcon, FunnelIcon, GaugeIcon, StackIcon, UsersIcon, WarningCircleIcon } from "@phosphor-icons/react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../../shared/api/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../shared/ui/card";
import { Button } from "../../shared/ui/button";
import { Text } from "@astryxdesign/core/Text";
import { Tabs, TabsList, TabsTrigger } from "../../shared/ui/tabs";
import { count, money, presetRange, settlementLabel, timestamp, validRange, type Group, type UsageRow, type UsageRows, type UsageSummary } from "./usage-data";
import "./usage-dashboard.css";

const groups: [Group, string][] = [["job", "작업별"], ["user", "사용자별"], ["call", "호출별"]];
const stateLabel: Record<string, string> = { settled: "정산 완료", reserved: "예약 중", uncertain: "확인 필요" };
function Id({ value }: { value: string }) {
  const [notice, setNotice] = useState("");
  return <span className="usage-id"><code title={value}>{value.length > 16 ? value.slice(0, 8) + "…" + value.slice(-6) : value}</code>
    <Button type="button" title={value + " 복사"} aria-label={value + " 복사"} onClick={async () => {
      try { await navigator.clipboard.writeText(value); setNotice("복사됨"); }
      catch { setNotice("복사 실패"); }
    }}><CopyIcon size={13} /></Button><span className="usage-copy-notice" role="status">{notice}</span></span>;
}

export default function UsageDashboard({ version, save }: {
  version: number; save: (path: string, payload: unknown) => Promise<unknown>;
}) {
  const [range, setRange] = useState(() => presetRange("7")), [preset, setPreset] = useState("7"),
    [user, setUser] = useState(""), [job, setJob] = useState(""), [jobDraft, setJobDraft] = useState(""),
    [group, setGroup] = useState<Group>("job"), [sort, setSort] = useState("cost"), [offset, setOffset] = useState(0),
    [refresh, setRefresh] = useState(0), [metric, setMetric] = useState("cost"),
    [summary, setSummary] = useState<UsageSummary | null>(null), [rows, setRows] = useState<UsageRows | null>(null),
    [summaryLoading, setSummaryLoading] = useState(true), [rowsLoading, setRowsLoading] = useState(true),
    [summaryError, setSummaryError] = useState(""), [rowsError, setRowsError] = useState(""), [rowsFor, setRowsFor] = useState(""),
    [manual, setManual] = useState<UsageRow | null>(null);
  const manualInput = useRef<HTMLInputElement>(null);
  const valid = validRange(range.start, range.end);
  const query = new URLSearchParams({ ...range, ...(user && { user_id: user }), ...(job && { job_id: job }) }).toString();
  const rowsQuery = `${query}&group_by=${group}&sort=${sort}&limit=25&offset=${offset}`;
  useEffect(() => {
    if (!valid) return;
    let live = true;
    setSummaryLoading(true); setSummaryError("");
    api("/api/admin/usage?" + query).then(decodeUsageSummary)
      .then(value => { if (live) setSummary(value); })
      .catch(e => { if (live) setSummaryError(e.message); })
      .finally(() => { if (live) setSummaryLoading(false); });
    return () => { live = false; };
  }, [query, valid, refresh, version]);
  useEffect(() => {
    if (!valid) return;
    let live = true;
    setRowsLoading(true); setRowsError(""); setManual(null);
    api("/api/admin/usage/rows?" + rowsQuery).then(decodeUsageRows)
      .then(value => { if (live) { setRows(value); setRowsFor(rowsQuery); } })
      .catch(e => { if (live) setRowsError(e.message); })
      .finally(() => { if (live) setRowsLoading(false); });
    return () => { live = false; };
  }, [rowsQuery, valid, refresh, version]);
  useEffect(() => { if (manual) manualInput.current?.focus(); }, [manual]);
  const chart = useMemo(() => {
    if (!summary) return [];
    const byDay = new Map(summary.daily.map(row => [row.day, row]));
    const result = [], date = new Date(range.start + "T00:00:00Z");
    if (!valid) return [];
    while (date.toISOString().slice(0, 10) <= range.end) {
      const day = date.toISOString().slice(0, 10), row = byDay.get(day);
      result.push({ day, spent: Number(row?.spent || 0), outstanding: Number(row?.outstanding || 0), calls: row?.calls || 0,
        incoming: row ? row.input_tokens : 0, outgoing: row ? row.output_tokens : 0 });
      date.setUTCDate(date.getUTCDate() + 1);
    }
    return result;
  }, [summary, range.start, range.end, valid]);
  function drill(row: UsageRow) {
    setUser(row.user_id); setJob(row.job_id || ""); setJobDraft(row.job_id || ""); setGroup("call"); setOffset(0);
  }
  function reset() {
    setRange(presetRange("7")); setPreset("7"); setUser(""); setJob(""); setJobDraft(""); setOffset(0);
  }
  const stats = summary?.summary, today = summary?.today;
  return <VStack gap={2} className="usage-dashboard">
    <header className="usage-heading"><div>
      <h2><ChartBarIcon size={20} aria-hidden /> 사용량과 비용</h2><p>기간부터 개별 호출까지, 사용 흐름을 확인하세요.</p></div>
      <Button variant="outline" onClick={() => setRefresh(v => v + 1)}><ArrowsClockwiseIcon size={16} />새로고침</Button></header>
    <HStack gap={2} wrap="wrap" className="usage-filters">
      <div><span><CalendarBlankIcon />조회 기간</span><NativeSelect aria-label="조회 기간" value={preset} onChange={e => {
        setPreset(e.target.value); if (e.target.value !== "custom") setRange(presetRange(e.target.value)); setOffset(0);
      }}><option value="today">오늘</option><option value="7">최근 7일</option><option value="30">최근 30일</option><option value="month">이번 달</option><option value="custom">직접 선택</option></NativeSelect></div>
      <Field label="시작일" inputID="usage-start"><input id="usage-start" className="admin-native-control" type="date" value={range.start} onChange={e => { setRange({ ...range, start: e.target.value }); setPreset("custom"); setOffset(0); }} /></Field>
      <Field label="종료일" inputID="usage-end"><input id="usage-end" className="admin-native-control" type="date" value={range.end} onChange={e => { setRange({ ...range, end: e.target.value }); setPreset("custom"); setOffset(0); }} /></Field>
      <VStack gap={2} className="usage-user-filter"><span><UsersIcon />사용자</span><NativeSelect aria-label="사용자 필터" value={user} onChange={e => { setUser(e.target.value); setOffset(0); }}>
        <option value="">전체 사용자</option>{summary?.users.map(item => <option key={item.id} value={item.id}>{item.id}</option>)}
      </NativeSelect></VStack>
      <form onSubmit={e => { e.preventDefault(); setJob(jobDraft.trim()); setOffset(0); }}><div>작업 ID<Input aria-label="작업 ID" type="search" placeholder="작업 ID로 좁히기" value={jobDraft} onChange={e => setJobDraft(e.target.value)} /></div><Button type="submit" variant="outline" aria-label="작업 필터 적용"><FunnelIcon size={16} /></Button></form>
      <Button variant="ghost" onClick={reset}>초기화</Button>
    </HStack>
    <HStack gap={2} wrap="wrap" className="usage-context"><span>한국 시간 (KST)</span><span>USD</span><span>최대 366일</span>{job && <Text type="supporting">작업 {job}</Text>}</HStack>
    {!valid ? <p role="alert">시작일과 종료일을 확인하세요. 최대 366일까지 조회할 수 있습니다.</p> : <>
      {summaryError ? <HStack gap={2} wrap="wrap" className="usage-error" role="alert"><WarningCircleIcon />{summaryError}<Button variant="outline" onClick={() => setRefresh(v => v + 1)}>다시 시도</Button></HStack> : summaryLoading ? <VStack gap={2} className="usage-loading" role="status">사용량을 불러오는 중…</VStack> : summary && stats && <>
        <div className="usage-cards">
          <Metric title="산정 비용" value={money(stats.spent)} icon={<CoinsIcon />} detail="정산 완료된 내부 산정액" accent />
          <Metric title="미확정 예약액" value={money(stats.outstanding)} icon={<GaugeIcon />} detail={<><span>확인 필요 {count(stats.uncertain)}건</span><span>호출 전 예약 {count(stats.pending_calls)}건</span></>} />
          <Metric title="API 호출 수" value={count(stats.calls)} icon={<StackIcon />} detail={<><span>시각을 기록한 호출</span><span>과거 호출 여부 미확인 {count(stats.unknown_calls)}건</span></>} />
          <Metric title="입력 / 출력 토큰" value={`${count(stats.input_tokens)} / ${count(stats.output_tokens)}`} icon={<ArrowRightIcon />} detail={<><span>입력 기록 {stats.input_recorded}건</span><span>출력 기록 {stats.output_recorded}건</span></>} />
        </div>
        <div className="usage-analysis">
          <Card className="usage-chart-card"><CardHeader><HStack gap={2} wrap="wrap" className="usage-chart-heading"><div><CardTitle>일별 사용 추이</CardTitle><CardDescription>{range.start} — {range.end}</CardDescription></div>
            <Tabs value={metric} onValueChange={setMetric}><TabsList aria-label="차트 지표"><TabsTrigger id="usage-chart-tab-cost" aria-controls="usage-chart-panel-cost" value="cost">비용</TabsTrigger><TabsTrigger id="usage-chart-tab-calls" aria-controls="usage-chart-panel-calls" value="calls">호출</TabsTrigger><TabsTrigger id="usage-chart-tab-tokens" aria-controls="usage-chart-panel-tokens" value="tokens">토큰</TabsTrigger></TabsList></Tabs></HStack></CardHeader>
            <CardContent id={`usage-chart-panel-${metric}`} role="tabpanel" aria-labelledby={`usage-chart-tab-${metric}`}><div className="usage-chart" role="group" aria-label={`일별 ${metric === "cost" ? "비용" : metric === "calls" ? "호출 수" : "토큰"} 차트. 아래 일별 수치에서 같은 정보를 확인할 수 있습니다.`}>
              <ResponsiveContainer width="100%" height={260} minWidth={0}><BarChart data={chart} accessibilityLayer margin={{ top: 8, right: 8, bottom: 4, left: 0 }}>
                <CartesianGrid vertical={false} stroke="var(--color-border)" /><XAxis dataKey="day" tickFormatter={v => v.slice(5).replace("-", "/")} tickLine={false} axisLine={false} minTickGap={24} fontSize={12} />
                <YAxis tickLine={false} axisLine={false} fontSize={12} width={64} tickFormatter={v => metric === "cost" ? `$${v}` : Number(v).toLocaleString("ko-KR", { notation: "compact" })} />
                <Tooltip formatter={(value, name) => [metric === "cost" ? money(Number(value).toFixed(8)) : count(Number(value)), name]} contentStyle={{ borderRadius: 12, borderColor: "var(--color-border)", fontSize: 12 }} /><Legend iconType="circle" wrapperStyle={{ fontSize: 12, paddingTop: 16 }} />
                {metric === "cost" ? <><Bar isAnimationActive={false} dataKey="spent" name="산정 비용" fill="var(--color-accent)" radius={[4, 4, 0, 0]} /><Bar isAnimationActive={false} dataKey="outstanding" name="미확정 예약액" fill="var(--color-data-purple-2)" radius={[4, 4, 0, 0]} /></> : metric === "calls" ? <Bar isAnimationActive={false} dataKey="calls" name="API 호출 수" fill="var(--color-accent)" radius={[4, 4, 0, 0]} /> : <><Bar isAnimationActive={false} dataKey="incoming" name="입력 토큰" fill="var(--color-accent)" radius={[4, 4, 0, 0]} /><Bar isAnimationActive={false} dataKey="outgoing" name="출력 토큰" fill="var(--color-data-purple-3)" radius={[4, 4, 0, 0]} /></>}
              </BarChart></ResponsiveContainer></div>
              <details className="usage-daily"><summary>일별 수치 보기</summary><div className="usage-table-scroll"><Table><caption className="sr-only">일별 사용량 수치</caption><TableHeader><TableRow><TableHeaderCell>날짜</TableHeaderCell><TableHeaderCell>산정 비용</TableHeaderCell><TableHeaderCell>미확정 예약액</TableHeaderCell><TableHeaderCell>호출</TableHeaderCell><TableHeaderCell>입력</TableHeaderCell><TableHeaderCell>출력</TableHeaderCell></TableRow></TableHeader><TableBody>{summary.daily.map(row => <TableRow key={row.day}><TableCell>{row.day}</TableCell><TableCell>{money(row.spent)}</TableCell><TableCell>{money(row.outstanding)}</TableCell><TableCell>{count(row.calls)}</TableCell><TableCell>{count(row.input_tokens)}</TableCell><TableCell>{count(row.output_tokens)}</TableCell></TableRow>)}</TableBody></Table>{!summary.daily.length && <p>이 기간의 사용량이 없습니다.</p>}</div></details>
            </CardContent></Card>
          <VStack gap={2} className="usage-side"><Card><CardHeader><CardTitle>캐시와 기록 상태</CardTitle><CardDescription>누락된 사용량은 0으로 계산하지 않습니다.</CardDescription></CardHeader><CardContent>
            <strong className="usage-cache">{count(stats.cached_tokens)}</strong><p>캐시 토큰은 입력 토큰에 포함됩니다.</p>
            <dl><div><dt>캐시 기록</dt><dd>원장 {stats.records}건 중 {stats.cached_recorded}건</dd></div><div><dt>토큰 기록 누락</dt><dd>{stats.missing_tokens}건</dd></div><div><dt>시각 기록 누락</dt><dd>{stats.missing_time}건</dd></div></dl>
          </CardContent></Card>
          <HStack gap={2} wrap="wrap" className="usage-note"><CheckCircleIcon size={18} /><p>산정 비용은 MAGI 내부 정책으로 계산한 금액입니다. OpenAI 청구 확정액과 다를 수 있습니다.</p></HStack></VStack>
        </div>
      </>}
      <Card className="usage-records"><CardHeader><HStack gap={2} wrap="wrap" className="usage-table-heading"><div><CardTitle>사용 내역</CardTitle><CardDescription>사용자와 작업에서 개별 호출까지 확인합니다.</CardDescription></div><div>정렬<NativeSelect aria-label="내역 정렬" value={sort} onChange={e => { setSort(e.target.value); setOffset(0); }}><option value="cost">비용순</option><option value="recent">최근순</option></NativeSelect></div></HStack>
        <Tabs value={group} onValueChange={value => { setGroup(value as Group); setOffset(0); }}><TabsList aria-label="내역 분류">{groups.map(([key, label]) => <TabsTrigger key={key} id={`usage-record-tab-${key}`} aria-controls={`usage-record-panel-${key}`} value={key}>{label}</TabsTrigger>)}</TabsList></Tabs></CardHeader>
        <CardContent id={`usage-record-panel-${group}`} role="tabpanel" aria-labelledby={`usage-record-tab-${group}`}>{rowsError ? <HStack gap={2} wrap="wrap" role="alert" className="usage-error">{rowsError}<Button variant="outline" onClick={() => setRefresh(v => v + 1)}>다시 시도</Button></HStack> : rowsLoading || rowsFor !== rowsQuery ? <p role="status">내역을 불러오는 중…</p> : !rows?.rows.length ? <VStack gap={2} className="usage-empty"><StackIcon size={28} /><h3>조회된 내역이 없습니다</h3><p>기간이나 사용자·작업 필터를 변경해 보세요.</p>{offset > 0 && <Button variant="outline" onClick={() => setOffset(0)}>첫 페이지로</Button>}</VStack> : <>
          <div className="usage-table-scroll" tabIndex={0} aria-label="사용 내역 표"><Table><caption className="sr-only">{groups.find(([key]) => key === group)?.[1]} 사용 내역, 한국 시간, USD</caption><TableHeader><TableRow>
            {group === "call" && <><TableHeaderCell>호출 시각 (KST)</TableHeaderCell><TableHeaderCell>모델 / 정산 상태</TableHeaderCell></>}
            {group !== "user" && <TableHeaderCell>작업</TableHeaderCell>}<TableHeaderCell>사용자 ID</TableHeaderCell>{group !== "call" && <TableHeaderCell>호출</TableHeaderCell>}<TableHeaderCell>입력 / 출력 토큰</TableHeaderCell><TableHeaderCell>산정 비용</TableHeaderCell><TableHeaderCell>미확정 예약액</TableHeaderCell><TableHeaderCell><span className="sr-only">작업</span></TableHeaderCell>
          </TableRow></TableHeader><TableBody>{rows.rows.map(row => <TableRow key={row.id || row.job_id + ":" + row.user_id}>
            {group === "call" && <><TableCell className="usage-nowrap">{timestamp(row.called_at)}<small>{row.usage_day}</small>{!row.is_call && <small>{row.reserved_at ? "호출 전 예약" : "호출 여부 미확인"}</small>}<small>예약 {timestamp(row.reserved_at)}</small></TableCell><TableCell><Text type="supporting">{stateLabel[row.state || ""] || row.state}</Text><small>{row.model}</small><small>{settlementLabel(row)}</small>{row.settled_at && <small>정산 {timestamp(row.settled_at)}</small>}</TableCell></>}
            {group !== "user" && <TableCell className="usage-job-cell"><Link to={"/admin/data?job_id=" + encodeURIComponent(row.job_id!)}>{row.request || "작업 제목 없음"}</Link><Id value={row.job_id!} /></TableCell>}
            <TableCell><Id value={row.user_id} /></TableCell>{group !== "call" && <TableCell>{count(row.calls)}<small>호출 전 예약 {row.pending_calls}건</small><small>미확인 {row.unknown_calls}건</small></TableCell>}
            <TableCell className="usage-nowrap">{count(row.input_tokens)} / {count(row.output_tokens)}<small>캐시 {count(row.cached_tokens)}</small>{group !== "call" && <small>토큰 누락 {row.missing_tokens}건</small>}</TableCell>
            <TableCell className="usage-amount">{money(row.spent)}</TableCell><TableCell className="usage-amount usage-muted">{money(row.outstanding)}</TableCell>
            <TableCell>{group !== "call" ? <Button variant="ghost" onClick={() => drill(row)}>호출 보기<ArrowRightIcon size={14} /></Button> : <><Id value={row.id!} />{row.state !== "settled" && <Button variant="outline" onClick={() => setManual(row)}>수동 정산</Button>}</>}</TableCell>
          </TableRow>)}</TableBody></Table></div>
          <HStack gap={2} wrap="wrap" className="usage-pagination"><HStack gap={2} wrap="wrap" className="usage-page-info"><span>전체 {count(rows.total)}건</span><span>{offset + 1}–{offset + rows.rows.length}</span></HStack><div><Button variant="outline" disabled={offset === 0} onClick={() => setOffset(v => Math.max(0, v - 25))}>이전</Button><Button variant="outline" disabled={offset + 25 >= rows.total} onClick={() => setOffset(v => v + 25)}>다음</Button></div></HStack>
        </>}</CardContent></Card>
    </>}
    <Card className="usage-management"><CardHeader><CardTitle>관측 기준과 정산 관리</CardTitle><CardDescription>사용량과 예상 비용을 관측합니다. 기준을 초과해도 실행을 제한하지 않습니다.</CardDescription></CardHeader><CardContent>
      {!summaryLoading && !summaryError && today && <HStack gap={2} wrap="wrap" className="usage-budget"><div><HStack gap={2} wrap="wrap" className="usage-page-info"><span>오늘</span><span>{today.day} (KST)</span></HStack><p><strong>{money(today.spent)}</strong> 산정 + {money(today.outstanding)} 예약 / {money(today.limit)}</p>
        <div className="usage-budget-track" role="meter" aria-label="오늘의 한도 사용률" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Number(today.limit) > 0 ? Math.min(100, (Number(today.spent) + Number(today.outstanding)) / Number(today.limit) * 100) : 0}><span style={{ width: `${Number(today.limit) > 0 ? Math.min(100, (Number(today.spent) + Number(today.outstanding)) / Number(today.limit) * 100) : 0}%` }} /></div></div>
        <form key={today.limit} onSubmit={e => { e.preventDefault(); void save("/api/admin/settings", { daily_usd: new FormData(e.currentTarget).get("daily_usd") }); }}><Field label="전체 일일 예상 비용 관측 기준 (US$)" inputID="usage-daily-usd"><input id="usage-daily-usd" className="admin-native-control" name="daily_usd" type="number" min="0" max="10000" step=".01" defaultValue={Number(today.limit)} required /></Field><Button type="submit" variant="default">관측 기준 저장</Button></form></HStack>}
      {manual ? <form className="usage-settle" onSubmit={async e => { e.preventDefault(); const result = await save("/api/admin/settle", { id: manual.id, actual: new FormData(e.currentTarget).get("actual") }); if (result) setManual(null); }}>
        <div><strong>수동 정산</strong><HStack gap={2} wrap="wrap" className="usage-page-info"><span>호출 <Id value={manual.id!} /></span><span>예약액 {money(manual.reserved)}</span></HStack><p>확인된 금액만 입력하세요. 토큰 수는 변경하지 않습니다.</p></div>
        <Field label="확인된 실제 비용 US$" inputID="usage-actual"><input id="usage-actual" className="admin-native-control" ref={manualInput} name="actual" type="number" min="0" max={manual.reserved} step=".00000001" required /></Field><Button type="submit" variant="default">정산 저장</Button><Button type="button" variant="ghost" onClick={() => setManual(null)}>취소</Button>
      </form> : <p className="usage-muted">수동 정산은 호출별 내역에서 미정산 기록을 선택하세요.</p>}
    </CardContent></Card>
  </VStack>;
}

function Metric({ title, value, detail, icon, accent }: { title: string; value: string; detail: React.ReactNode; icon: React.ReactNode; accent?: boolean }) {
  return <Card className={"usage-metric" + (accent ? " usage-metric-accent" : "")}><CardHeader><CardDescription>{title}{icon}</CardDescription><CardTitle>{value}</CardTitle></CardHeader><CardContent><HStack gap={2} wrap="wrap" className="usage-metric-details">{detail}</HStack></CardContent></Card>;
}
