import { useEffect, useState } from "react";
import { CopyrightIcon, DownloadSimpleIcon, ArrowLeftIcon } from "@phosphor-icons/react";
import { Button } from "./components/ui/button";
import { Notice } from "./UI";

type LicenseEntry = { name: string; version: string; license: string; url: string; text: string };

export function Licenses() {
  const [entries, setEntries] = useState<LicenseEntry[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    fetch("/static/vendor/third-party-licenses.json", { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error("라이선스 고지를 불러오지 못했습니다.");
        return response.json();
      }).then(setEntries).catch((cause) => { if (cause.name !== "AbortError") setError(cause.message); });
    return () => controller.abort();
  }, []);
  return <main className="licenses-page">
    <a className="brand" href="/">MAGI</a>
    <header><span className="eyebrow">OPEN SOURCE ACKNOWLEDGEMENTS</span><h1><CopyrightIcon weight="duotone" size={32} aria-hidden /> 오픈소스 라이선스</h1>
      <p>MAGI의 화면을 구성하는 오픈소스 코드와 에셋의 저작권 고지입니다. 각 항목을 펼치면 배포에 포함된 라이선스 원문을 확인할 수 있습니다.</p>
      <Button asChild variant="outline"><a href="/static/vendor/THIRD_PARTY_NOTICES.txt" download><DownloadSimpleIcon size={18} aria-hidden />전체 고지 다운로드</a></Button>
    </header>
    {error ? <Notice>{error}</Notice> : entries.length === 0 ? <p role="status">라이선스 고지를 불러오는 중입니다.</p> : <p className="subtle">배포 코드·에셋 {entries.length}개 · 라이선스 원문은 원문 언어로 제공합니다.</p>}
    {entries.map((entry) => <details className="license-entry" key={`${entry.name}:${entry.version}`}><summary>{entry.name}<small>{entry.license}</small></summary><div><p className="subtle">버전 / 출처 리비전: {entry.version}</p>{entry.url.startsWith("https://") && <a href={entry.url} target="_blank" rel="noreferrer">공식 소스</a>}<pre>{entry.text}</pre></div></details>)}
    <footer className="public-links"><a href="/"><ArrowLeftIcon size={14} aria-hidden /> 작업 공간으로</a><a href="/privacy">정보 처리 안내</a></footer>
  </main>;
}
