import { HStack } from "@astryxdesign/core/HStack";
import { useEffect, useState } from "react";
import { CopyrightIcon, DownloadSimpleIcon } from "@phosphor-icons/react";
import { WorkspaceReturnLink } from "../workspace/WorkspaceReturnLink";
import { Button } from "../../shared/ui/button";
import { Notice } from "../../shared/ui/UI";
import "./research.css";

type LicenseEntry = { name: string; version: string; license: string; url: string; text: string };

export function Licenses() {
  // 2026-11-09: 응답 전과 성공적으로 조회된 빈 목록을 구분해 로딩 상태가 남지 않게 한다.
  const [entries, setEntries] = useState<LicenseEntry[] | null>(null);
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
    <header><h1><CopyrightIcon weight="duotone" size={32} aria-hidden /> 오픈소스 라이선스</h1>
      <p>MAGI의 화면·서버를 구성하는 오픈소스 코드와 에셋의 저작권 고지입니다. 각 항목을 펼치면 배포에 포함된 라이선스 원문을 확인할 수 있습니다.</p>
      <Button asChild variant="outline"><a href="/static/vendor/THIRD_PARTY_NOTICES.txt" download><DownloadSimpleIcon size={18} aria-hidden />전체 고지 다운로드</a></Button>
    </header>
    <h2>배포에 포함된 라이선스</h2>
    {error ? <Notice>{error}</Notice> : entries === null ? <p role="status">라이선스 고지를 불러오는 중입니다.</p> : entries.length === 0 ? <p role="status">표시할 라이선스 고지가 없습니다.</p> : <HStack gap={2} wrap="wrap" className="license-overview"><p>배포 코드와 에셋 <strong>{entries.length}개</strong></p><p>라이선스 원문은 원문 언어로 제공합니다.</p></HStack>}
    {entries?.map((entry) => <details className="license-entry" key={`${entry.name}:${entry.version}`}><summary>{entry.name}<small>{entry.license}</small></summary><div><p className="subtle">버전 / 출처 리비전: {entry.version}</p>{entry.url.startsWith("https://") && <a href={entry.url} target="_blank" rel="noreferrer">공식 소스</a>}<pre>{entry.text}</pre></div></details>)}
    <footer className="public-links"><WorkspaceReturnLink /><a href="/privacy">정보 처리 안내</a><a href="/research">연구 출처 및 적용 방식</a></footer>
  </main>;
}
