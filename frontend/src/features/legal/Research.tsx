import { BookOpenIcon } from "@phosphor-icons/react";
import { WorkspaceReturnLink } from "../workspace/WorkspaceReturnLink";
import "./research.css";

export function Research() {
  return <main className="research-page">
    <a className="brand" href="/">MAGI</a>
    <header>
      <span className="eyebrow">RESEARCH & APPLICATION</span>
      <h1><BookOpenIcon weight="duotone" size={32} aria-hidden />연구 출처 및 적용 방식</h1>
      <p>MAGI는 RubricRefine의 작업별 검사 기준과 항목별 피드백을 활용하는 접근을 참고해, 요구사항에 근거한 명세 검토에 응용했습니다.</p>
    </header>
    <section aria-labelledby="research-source">
      <h2 id="research-source">참고 논문</h2>
      <p lang="en"><cite>RubricRefine: Improving Tool-Use Agent Reliability with Training-Free Pre-Execution Refinement</cite></p>
      <p lang="en">Will LeVine, Brendan Raffel Evers, Sam Saltwick, Abhay Venkatesh</p>
      <p>2026년 · arXiv:2605.09730v5</p>
      <a href="https://arxiv.org/html/2605.09730v5" target="_blank" rel="noreferrer">논문 원문 보기 (v5, 새 창)</a>
    </section>
    <section aria-labelledby="research-method">
      <h2 id="research-method">참고한 방법</h2>
      <p>논문은 작업과 도구 문서에 맞춰 검사 기준인 루브릭을 만들고, 실행 전 코드 후보를 항목별로 평가합니다. 평가 이유와 수정 지시를 다음 개선에 활용하며, 같은 작업의 개선 과정에서는 기준을 유지합니다.</p>
    </section>
    <section aria-labelledby="research-application">
      <h2 id="research-application">MAGI에서는 이렇게 적용합니다</h2>
      <ol>
        <li><strong>확정 요구사항에서 검사 기준 생성</strong><p>요구사항과 제약에 근거한 기준을 만들고, 각 기준을 해당 요구사항의 인용과 연결합니다.</p></li>
        <li><strong>명세 초안 평가</strong><p>기준별로 명세의 해당 부분을 검토하고, 근거 인용과 함께 충족·미충족·판단 불가로 판정합니다. 근거가 없는 경우에는 누락 사실을 평가에 기록합니다.</p></li>
        <li><strong>수정 흐름 연결</strong><p>미충족 또는 판단 불가 항목을 검토 이슈에 연결해 기존 수정·재검토 흐름에서 다룹니다.</p></li>
        <li><strong>승인 전 최신 평가 확인</strong><p>현재 요구사항과 초안에 대응하는 평가인지 확인하고, 모든 검사 항목이 충족된 경우에만 승인 단계로 진행합니다.</p></li>
      </ol>
    </section>
    <section aria-labelledby="research-design">
      <h2 id="research-design">MAGI에서 자체 설계한 부분</h2>
      <ul>
        <li>같은 확정 입력에서는 검사 기준을 재사용하고, 요구사항 등 기준 생성의 근거가 바뀌면 갱신합니다.</li>
        <li>기준의 인용이 요구사항에 존재하는지, 평가 인용이 지정된 명세 부분에 실제로 존재하는지 검사합니다.</li>
        <li>점수 대신 충족·미충족·판단 불가 판정을 사용하며, 승인 시 최신 초안에 대한 전 항목 충족을 요구합니다.</li>
      </ul>
    </section>
    <section aria-labelledby="research-limits">
      <h2 id="research-limits">적용 범위와 한계</h2>
      <p>논문의 도구 실행 전 코드 검사 접근을 MAGI의 명세 검토에 맞춰 응용했습니다. MAGI가 검토하는 대상은 명세이며, 구현 코드의 실행 결과를 검증하는 것은 아닙니다.</p>
      <p>논문의 전체 알고리즘을 그대로 재현한 것은 아니며, 논문에서 보고한 성능을 MAGI에서도 달성했다고 주장하지 않습니다. AI 평가와 인용 검사는 의미적 정확성이나 요구사항의 완전성을 보장하지 않으므로 최종 명세는 사용자의 검토가 필요합니다.</p>
      <p>이 페이지는 연구 출처와 응용 방식을 설명합니다. 배포 코드·에셋의 저작권과 라이선스 고지는 별도의 오픈소스 라이선스 페이지에서 제공합니다.</p>
    </section>
    <footer className="public-links"><WorkspaceReturnLink /><a href="/licenses">오픈소스 라이선스</a><a href="/privacy">정보 처리 안내</a></footer>
  </main>;
}
