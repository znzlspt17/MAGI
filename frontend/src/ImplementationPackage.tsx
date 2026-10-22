import { useEffect, useRef, useState } from "react";
import { ArchiveIcon, FileTextIcon, DownloadSimpleIcon, CaretDownIcon } from "@phosphor-icons/react";
import { api, apiBlob } from "./api";
import { Button } from "./UI";
import { Dialog, DialogTrigger, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "./components/ui/dialog";
import { ItemGroup, Item, ItemContent, ItemTitle, ItemDescription } from "./components/ui/item";
import { Badge } from "./components/ui/badge";
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "./components/ui/collapsible";
import { Alert, AlertDescription } from "./components/ui/alert";
import { Empty, EmptyHeader, EmptyTitle, EmptyDescription } from "./components/ui/empty";
import { Skeleton } from "./components/ui/skeleton";
import "./implementation-package.css";

export type PackageMetadata = { completed_id: string; bundle_id: string; filename: string; available: boolean; completeness: string; korean_included: boolean; task_count: number; total_size: number; source_hash: string; files: { name: string; size: number; sha256: string }[]; limitations: string[] };
const descriptions: Record<string, string> = { "README.ko.md": "읽는 순서와 자료 범위", "SPEC.en.md": "승인된 영어 명세 원문", "SPEC.ko.md": "저장·검증된 해당 버전의 한국어 번역", "TASKS.md": "구현 순서와 완료 조건", "CONSTRAINTS.md": "제품 제약·비범위·금지 동작", "VERIFICATION.md": "실행 전 검증 계획 · 실제 결과 미수집", "manifest.json": "버전·파일 크기·SHA-256" };
const sizeLabel = (bytes: number) => bytes < 1024 ? `${bytes} B` : bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KiB` : `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;

export function ImplementationPackage({ jobId, completedId, label = "구현 묶음 다운로드" }: { jobId: string; completedId?: string; label?: string }) {
  const [open, setOpen] = useState(false), [data, setData] = useState<PackageMetadata | null>(null), [error, setError] = useState(""), [loading, setLoading] = useState(false), [downloading, setDownloading] = useState(false), [retry, setRetry] = useState(0), [done, setDone] = useState(false);
  const generation = useRef(0), transfer = useRef<AbortController | null>(null), sending = useRef(false);
  const base = `/api/jobs/${encodeURIComponent(jobId)}/implementation-package`;
  useEffect(() => { setOpen(false); setData(null); setDone(false); }, [jobId, completedId]);
  useEffect(() => {
    const ticket = ++generation.current;
    setData(null); setError(""); setDone(false); setDownloading(false); sending.current = false;
    transfer.current?.abort();
    if (!open) return;
    const controller = new AbortController(); setLoading(true);
    const search = new URLSearchParams(completedId ? { completed_id: completedId } : {});
    void api<PackageMetadata>(`${base}?${search}`, { signal: controller.signal }).then(value => {
      if (ticket === generation.current && !controller.signal.aborted) setData(value);
    }).catch(e => { if (!controller.signal.aborted && ticket === generation.current && e.status !== 404) setError(e.message); }).finally(() => {
      if (!controller.signal.aborted && ticket === generation.current) setLoading(false);
    });
    return () => { controller.abort(); transfer.current?.abort(); generation.current++; };
  }, [jobId, completedId, open, retry]);
  async function download() {
    if (!data?.available || sending.current) return;
    sending.current = true; setDownloading(true); setError(""); setDone(false);
    const controller = new AbortController(); transfer.current = controller;
    const ticket = generation.current;
    try {
      const search = new URLSearchParams({ completed_id: data.completed_id, bundle_id: data.bundle_id });
      const blob = await apiBlob(`${base}/download?${search}`, controller.signal);
      if (controller.signal.aborted || ticket !== generation.current) return;
      const url = URL.createObjectURL(blob), link = document.createElement("a");
      link.href = url; link.download = data.filename; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 0); setDone(true);
    } catch (e) { if (!controller.signal.aborted && ticket === generation.current) setError((e as Error).message); }
    finally { if (ticket === generation.current) { sending.current = false; setDownloading(false); } }
  }
  return <Dialog open={open} onOpenChange={value => { if (value) setLoading(true); setOpen(value); }}><DialogTrigger asChild><Button><ArchiveIcon size={17} aria-hidden />{label}</Button></DialogTrigger><DialogContent className="implementation-package"><DialogHeader><DialogTitle>구현 시작용 파일 묶음</DialogTitle><DialogDescription>승인된 버전의 명세·작업 순서·제약·검증 계획을 ZIP으로 받습니다.</DialogDescription></DialogHeader>
    {loading && <div role="status" aria-label="포함 자료 조회 중"><Skeleton className="h-12 w-full" /></div>}
    {error && <Alert role="alert"><AlertDescription>{error}</AlertDescription></Alert>}
    {!loading && !data && !error && <Empty><EmptyHeader><EmptyTitle>승인된 명세가 없습니다</EmptyTitle><EmptyDescription>명세를 승인한 뒤 파일 묶음을 받을 수 있습니다.</EmptyDescription></EmptyHeader></Empty>}
    {data && <><div className="package-badges"><Badge variant="secondary">승인본 {data.completed_id.slice(0, 12)}</Badge><Badge variant="outline">영어 원문 기준</Badge><Badge variant="outline">{data.korean_included ? "저장된 한국어 번역 포함" : "저장된 번역 없음 · 영어 원문 포함"}</Badge><Badge variant="outline">{data.completeness === "complete" ? `구조화 작업 ${data.task_count}개` : "작업 연결 자료 부족"}</Badge></div>
      <Collapsible><CollapsibleTrigger className="package-version">버전 전체 값과 해시<CaretDownIcon size={14} aria-hidden /></CollapsibleTrigger><CollapsibleContent><dl><dt>승인 완료본</dt><dd>{data.completed_id}</dd><dt>명세 SHA-256</dt><dd>{data.source_hash}</dd><dt>묶음 식별값</dt><dd>{data.bundle_id}</dd></dl></CollapsibleContent></Collapsible>
      {!!data.limitations.length && <Alert><AlertDescription>{data.limitations.map((line, i) => <p key={i}>{line}</p>)}</AlertDescription></Alert>}
      <ItemGroup className="package-files">{data.files.map(file => <Item key={file.name} variant="outline" size="sm"><FileTextIcon size={19} aria-hidden /><ItemContent><ItemTitle>{file.name}</ItemTitle><ItemDescription>{descriptions[file.name]}</ItemDescription></ItemContent><span className="package-file-size">{sizeLabel(file.size)}</span></Item>)}</ItemGroup><p className="package-note">전체 자료 {sizeLabel(data.total_size)} · 실제 테스트 결과는 수집하지 않았습니다.</p>
    </>}
    <p role="status">{downloading ? "ZIP을 준비하고 전송하고 있습니다." : done ? "브라우저에 ZIP 다운로드를 전달했습니다." : ""}</p>
    <DialogFooter><Button disabled={loading || downloading} onClick={() => setRetry(v => v + 1)}>포함 자료 다시 조회</Button><Button className="primary" disabled={!data?.available || loading || downloading} onClick={() => void download()}><DownloadSimpleIcon size={17} aria-hidden />ZIP 받기</Button></DialogFooter>
  </DialogContent></Dialog>;
}
