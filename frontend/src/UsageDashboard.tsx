// shadcn/ui dashboard-01의 요약 카드·차트·데이터 표 구성을 MAGI에 맞게 적용한다(MIT).
// https://github.com/shadcn-ui/ui/tree/ba1503c64472b82256d9de95e2e62c5901a38e8b
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowsClockwiseIcon, ArrowRightIcon, CalendarBlankIcon, ChartBarIcon, CheckCircleIcon, CoinsIcon, CopyIcon, FunnelIcon, GaugeIcon, StackIcon, UsersIcon, WarningCircleIcon } from "@phosphor-icons/react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "./api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./components/ui/card";
import { Button } from "./components/ui/button";
import { Badge } from "./components/ui/badge";
import { Tabs, TabsList, TabsTrigger } from "./components/ui/tabs";
import { count, money, presetRange, settlementLabel, timestamp, validRange, type Group, type UsageRow, type UsageRows, type UsageSummary } from "./usage-data";
import "./usage-dashboard.css";

const groups: [Group, string][] = [["job", "작업별"], ["user", "사용자별"], ["call", "호출별"]];
const stateLabel: Record<string, string> = { settled: "정산 완료", reserved: "예약 중", uncertain: "확인 필요" };
function Id({ value }: { value: string }) {
  const [notice, setNotice] = useState("");
  return <span className="usage-id"><code title={value}>{value.length > 16 ? value.slice(0, 8) + "…" + value.slice(-6) : value}</code>
    <button type="button" title={value + " 복사"} aria-label={value + " 복사"} onClick={async () => {
      try { await navigator.clipboard.writeText(value); setNotice("복사됨"); }
      catch { setNotice("복사 실패"); }
    }}><CopyIcon size={13} /></button><span className="usage-copy-notice" role="status">{notice}</span></span>;
}

export default function UsageDashboard({ version, save }: {
  version: number; save: (path: string, payload: unknown) => Promise<any>;
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
    api<UsageSummary>("/api/admin/usage?" + query)
      .then(value => { if (live) setSummary(value); })
      .catch(e => { if (live) setSummaryError(e.message); })
      .finally(() => { if (live) setSummaryLoading(false); });
    return () => { live = false; };
  }, [query, valid, refresh, version]);
  useEffect(() => {
    if (!valid) return;
    let live = true;
    setRowsLoading(true); setRowsError(""); setManual(null);
    api<UsageRows>("/api/admin/usage/rows?" + rowsQuery)
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
  return <div className="usage-dashboard">
    <header className="usage-heading"><div><span className="usage-eyebrow"><ChartBarIcon size={16} /> USAGE & LIMITS</span>
      <h2>사용량과 비용</h2><p>기간부터 개별 호출까지, 사용 흐름을 확인하세요.</p></div>
      <Button variant="outline" onClick={() => setRefresh(v => v + 1)}><ArrowsClockwiseIcon size={16} />새로고침</Button></header>
    <div className="usage-filters">
      <label><span><CalendarBlankIcon />조회 기간</span><select aria-label="조회 기간" value={preset} onChange={e => {
        setPreset(e.target.value); if (e.target.value !== "custom") setRange(presetRange(e.target.value)); setOffset(0);
      }}><option value="today">오늘</option><option value="7">최근 7일</option><option value="30">최근 30일</option><option value="month">이번 달</option><option value="custom">직접 선택</option></select></label>
      <label>시작일<input aria-label="시작일" type="date" value={range.start} onChange={e => { setRange({ ...range, start: e.target.value }); setPreset("custom"); setOffset(0); }} /></label>
      <label>종료일<input aria-label="종료일" type="date" value={range.end} onChange={e => { setRange({ ...range, end: e.target.value }); setPreset("custom"); setOffset(0); }} /></label>
      <label className="usage-user-filter"><span><UsersIcon />사용자</span><select aria-label="사용자 필터" value={user} onChange={e => { setUser(e.target.value); setOffset(0); }}>
        <option value="">전체 사용자</option>{summary?.users.map(item => <option key={item.id} value={item.id}>{item.id}</option>)}
      </select></label>
      <form onSubmit={e => { e.preventDefault(); setJob(jobDraft.trim()); setOffset(0); }}><label>작업 ID<input type="search" placeholder="작업 ID로 좁히기" value={jobDraft} onChange={e => setJobDraft(e.target.value)} /></label><Button variant="outline" aria-label="작업 필터 적용"><FunnelIcon size={16} /></Button></form>
      <Button variant="ghost" onClick={reset}>초기화</Button>
    </div>
    <div className="usage-context"><span>한국 시간 (KST) · USD · 최대 366일</span>{job && <Badge variant="secondary">작업 {job}</Badge>}</div>
    {!valid ? <p role="alert">시작일과 종료일을 확인하세요. 최대 366일까지 조회할 수 있습니다.</p> : <>
      {summaryError ? <div className="usage-error" role="alert"><WarningCircleIcon />{summaryError}<Button variant="outline" onClick={() => setRefresh(v => v + 1)}>다시 시도</Button></div> : summaryLoading ? <div className="usage-loading" role="status">사용량을 불러오는 중…</div> : summary && stats && <>
        <div className="usage-cards">
          <Metric title="산정 비용" value={money(stats.spent)} icon={<CoinsIcon />} detail="정산 완료된 내부 산정액" accent />
          <Metric title="미확정 예약액" value={money(stats.outstanding)} icon={<GaugeIcon />} detail={`확인 필요 ${count(stats.uncertain)}건 · 호출 전 예약 ${count(stats.pending_calls)}건`} />
          <Metric title="API 호출 수" value={count(stats.calls)} icon={<StackIcon />} detail={`시각을 기록한 호출 · 과거 호출 여부 미확인 ${count(stats.unknown_calls)}건`} />
          <Metric title="입력 / 출력 토큰" value={`${count(stats.input_tokens)} / ${count(stats.output_tokens)}`} icon={<ArrowRightIcon />} detail={`입력 기록 ${stats.input_recorded}건 · 출력 기록 ${stats.output_recorded}건`} />
        </div>
        <div className="usage-analysis">
          <Card className="usage-chart-card"><CardHeader><div className="usage-chart-heading"><div><CardTitle>일별 사용 추이</CardTitle><CardDescription>{range.start} — {range.end}</CardDescription></div>
            <Tabs value={metric} onValueChange={setMetric}><TabsList aria-label="차트 지표"><TabsTrigger value="cost">비용</TabsTrigger><TabsTrigger value="calls">호출</TabsTrigger><TabsTrigger value="tokens">토큰</TabsTrigger></TabsList></Tabs></div></CardHeader>
            <CardContent><div className="usage-chart" role="group" aria-label={`일별 ${metric === "cost" ? "비용" : metric === "calls" ? "호출 수" : "토큰"} 차트. 아래 일별 수치에서 같은 정보를 확인할 수 있습니다.`}>
              <ResponsiveContainer width="100%" height={260} minWidth={0}><BarChart data={chart} accessibilityLayer margin={{ top: 8, right: 8, bottom: 4, left: 0 }}>
                <CartesianGrid vertical={false} stroke="#ece9f2" /><XAxis dataKey="day" tickFormatter={v => v.slice(5).replace("-", "/")} tickLine={false} axisLine={false} minTickGap={24} fontSize={12} />
                <YAxis tickLine={false} axisLine={false} fontSize={11} width={64} tickFormatter={v => metric === "cost" ? `$${v}` : Number(v).toLocaleString("ko-KR", { notation: "compact" })} />
                <Tooltip formatter={(value, name) => [metric === "cost" ? money(Number(value).toFixed(8)) : count(Number(value)), name]} contentStyle={{ borderRadius: 12, borderColor: "#e7e4ec", fontSize: 12 }} /><Legend iconType="circle" wrapperStyle={{ fontSize: 12, paddingTop: 16 }} />
                {metric === "cost" ? <><Bar isAnimationActive={false} dataKey="spent" name="산정 비용" fill="#7955d9" radius={[4, 4, 0, 0]} /><Bar isAnimationActive={false} dataKey="outstanding" name="미확정 예약액" fill="#d2c5f3" radius={[4, 4, 0, 0]} /></> : metric === "calls" ? <Bar isAnimationActive={false} dataKey="calls" name="API 호출 수" fill="#7955d9" radius={[4, 4, 0, 0]} /> : <><Bar isAnimationActive={false} dataKey="incoming" name="입력 토큰" fill="#7955d9" radius={[4, 4, 0, 0]} /><Bar isAnimationActive={false} dataKey="outgoing" name="출력 토큰" fill="#48a6a0" radius={[4, 4, 0, 0]} /></>}
              </BarChart></ResponsiveContainer></div>
              <details className="usage-daily"><summary>일별 수치 보기</summary><div className="usage-table-scroll"><table><caption className="sr-only">일별 사용량 수치</caption><thead><tr><th>날짜</th><th>산정 비용</th><th>미확정 예약액</th><th>호출</th><th>입력</th><th>출력</th></tr></thead><tbody>{summary.daily.map(row => <tr key={row.day}><td>{row.day}</td><td>{money(row.spent)}</td><td>{money(row.outstanding)}</td><td>{count(row.calls)}</td><td>{count(row.input_tokens)}</td><td>{count(row.output_tokens)}</td></tr>)}</tbody></table>{!summary.daily.length && <p>이 기간의 사용량이 없습니다.</p>}</div></details>
            </CardContent></Card>
          <div className="usage-side"><Card><CardHeader><CardTitle>캐시와 기록 상태</CardTitle><CardDescription>누락된 사용량은 0으로 계산하지 않습니다.</CardDescription></CardHeader><CardContent>
            <strong className="usage-cache">{count(stats.cached_tokens)}</strong><p>캐시 토큰 · 입력 토큰에 포함</p>
            <dl><div><dt>캐시 기록</dt><dd>원장 {stats.records}건 중 {stats.cached_recorded}건</dd></div><div><dt>토큰 기록 누락</dt><dd>{stats.missing_tokens}건</dd></div><div><dt>시각 기록 누락</dt><dd>{stats.missing_time}건</dd></div></dl>
          </CardContent></Card>
          <div className="usage-note"><CheckCircleIcon size={18} /><p>산정 비용은 MAGI 내부 정책으로 계산한 금액입니다. OpenAI 청구 확정액과 다를 수 있습니다.</p></div></div>
        </div>
      </>}
      <Card className="usage-records"><CardHeader><div className="usage-table-heading"><div><CardTitle>사용 내역</CardTitle><CardDescription>사용자와 작업에서 개별 호출까지 확인합니다.</CardDescription></div><label>정렬<select aria-label="내역 정렬" value={sort} onChange={e => { setSort(e.target.value); setOffset(0); }}><option value="cost">비용순</option><option value="recent">최근순</option></select></label></div>
        <Tabs value={group} onValueChange={value => { setGroup(value as Group); setOffset(0); }}><TabsList aria-label="내역 분류">{groups.map(([key, label]) => <TabsTrigger key={key} value={key}>{label}</TabsTrigger>)}</TabsList></Tabs></CardHeader>
        <CardContent>{rowsError ? <div role="alert" className="usage-error">{rowsError}<Button variant="outline" onClick={() => setRefresh(v => v + 1)}>다시 시도</Button></div> : rowsLoading || rowsFor !== rowsQuery ? <p role="status">내역을 불러오는 중…</p> : !rows?.rows.length ? <div className="usage-empty"><StackIcon size={28} /><h3>조회된 내역이 없습니다</h3><p>기간이나 사용자·작업 필터를 변경해 보세요.</p>{offset > 0 && <Button variant="outline" onClick={() => setOffset(0)}>첫 페이지로</Button>}</div> : <>
          <div className="usage-table-scroll" tabIndex={0} aria-label="사용 내역 표"><table><caption className="sr-only">{groups.find(([key]) => key === group)?.[1]} 사용 내역 · 한국 시간 · USD</caption><thead><tr>
            {group === "call" && <><th>호출 시각 (KST)</th><th>모델 / 정산 상태</th></>}
            {group !== "user" && <th>작업</th>}<th>사용자 ID</th>{group !== "call" && <th>호출</th>}<th>입력 / 출력 토큰</th><th>산정 비용</th><th>미확정 예약액</th><th><span className="sr-only">작업</span></th>
          </tr></thead><tbody>{rows.rows.map(row => <tr key={row.id || row.job_id + ":" + row.user_id}>
            {group === "call" && <><td className="usage-nowrap">{timestamp(row.called_at)}<small>{row.usage_day}{row.is_call ? "" : row.reserved_at ? " · 호출 전 예약" : " · 호출 여부 미확인"}</small><small>예약 {timestamp(row.reserved_at)}</small></td><td><Badge variant={row.state === "settled" ? "secondary" : "outline"}>{stateLabel[row.state || ""] || row.state}</Badge><small>{row.model}</small><small>{settlementLabel(row)}</small>{row.settled_at && <small>정산 {timestamp(row.settled_at)}</small>}</td></>}
            {group !== "user" && <td className="usage-job-cell"><Link to={"/admin/data?job_id=" + encodeURIComponent(row.job_id!)}>{row.request || "작업 제목 없음"}</Link><Id value={row.job_id!} /></td>}
            <td><Id value={row.user_id} /></td>{group !== "call" && <td>{count(row.calls)}<small>호출 전 예약 {row.pending_calls}건 · 미확인 {row.unknown_calls}건</small></td>}
            <td className="usage-nowrap">{count(row.input_tokens)} / {count(row.output_tokens)}<small>캐시 {count(row.cached_tokens)}{group !== "call" && ` · 토큰 누락 ${row.missing_tokens}건`}</small></td>
            <td className="usage-amount">{money(row.spent)}</td><td className="usage-amount usage-muted">{money(row.outstanding)}</td>
            <td>{group !== "call" ? <Button variant="ghost" onClick={() => drill(row)}>호출 보기<ArrowRightIcon size={14} /></Button> : <><Id value={row.id!} />{row.state !== "settled" && <Button variant="outline" onClick={() => setManual(row)}>수동 정산</Button>}</>}</td>
          </tr>)}</tbody></table></div>
          <div className="usage-pagination"><span>전체 {count(rows.total)}건 · {offset + 1}–{offset + rows.rows.length}</span><div><Button variant="outline" disabled={offset === 0} onClick={() => setOffset(v => Math.max(0, v - 25))}>이전</Button><Button variant="outline" disabled={offset + 25 >= rows.total} onClick={() => setOffset(v => v + 25)}>다음</Button></div></div>
        </>}</CardContent></Card>
    </>}
    <Card className="usage-management"><CardHeader><CardTitle>관측 기준과 정산 관리</CardTitle><CardDescription>사용량과 예상 비용을 관측합니다. 기준을 초과해도 실행을 제한하지 않습니다.</CardDescription></CardHeader><CardContent>
      {!summaryLoading && !summaryError && today && <div className="usage-budget"><div><span>오늘 · {today.day} (KST)</span><p><strong>{money(today.spent)}</strong> 산정 + {money(today.outstanding)} 예약 / {money(today.limit)}</p>
        <div className="usage-budget-track" role="meter" aria-label="오늘의 한도 사용률" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Number(today.limit) > 0 ? Math.min(100, (Number(today.spent) + Number(today.outstanding)) / Number(today.limit) * 100) : 0}><span style={{ width: `${Number(today.limit) > 0 ? Math.min(100, (Number(today.spent) + Number(today.outstanding)) / Number(today.limit) * 100) : 0}%` }} /></div></div>
        <form key={today.limit} onSubmit={e => { e.preventDefault(); void save("/api/admin/settings", { daily_usd: new FormData(e.currentTarget).get("daily_usd") }); }}><label>전체 일일 예상 비용 관측 기준 (US$)<input name="daily_usd" type="number" min="0" max="10000" step=".01" defaultValue={Number(today.limit)} required /></label><Button variant="outline">관측 기준 저장</Button></form></div>}
      {manual ? <form className="usage-settle" onSubmit={async e => { e.preventDefault(); const result = await save("/api/admin/settle", { id: manual.id, actual: new FormData(e.currentTarget).get("actual") }); if (result) setManual(null); }}>
        <div><strong>수동 정산</strong><p>호출 <Id value={manual.id!} /> · 예약액 {money(manual.reserved)}</p><p>확인된 금액만 입력하세요. 토큰 수는 변경하지 않습니다.</p></div>
        <label>확인된 실제 비용 US$<input ref={manualInput} name="actual" type="number" min="0" max={manual.reserved} step=".00000001" required /></label><Button>정산 저장</Button><Button type="button" variant="ghost" onClick={() => setManual(null)}>취소</Button>
      </form> : <p className="usage-muted">수동 정산은 호출별 내역에서 미정산 기록을 선택하세요.</p>}
    </CardContent></Card>
  </div>;
}

function Metric({ title, value, detail, icon, accent }: { title: string; value: string; detail: string; icon: React.ReactNode; accent?: boolean }) {
  return <Card className={"usage-metric" + (accent ? " usage-metric-accent" : "")}><CardHeader><CardDescription>{title}{icon}</CardDescription><CardTitle>{value}</CardTitle></CardHeader><CardContent><p>{detail}</p></CardContent></Card>;
}
