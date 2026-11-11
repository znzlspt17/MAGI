import { BookOpenIcon } from "@phosphor-icons/react";
import { WorkspaceReturnLink } from "../workspace/WorkspaceReturnLink";
import "./research.css";

const paper = "https://arxiv.org/html/2605.09730v5";
const sections = [
  ["abstract", "초록과 적용 범위"], ["background", "연구 배경과 문제 정의"],
  ["paper", "원 논문의 방법과 실험"], ["comparison", "논문과 MAGI의 대응 관계"],
  ["generation", "작업별 루브릭 생성"], ["evaluation", "항목별 평가와 근거"],
  ["score", "점수와 중요 실패 제한"], ["iteration", "반복 수정과 후보 선택"],
  ["roles", "단계별 책임과 근거 우선순위"], ["storage", "보존·복구·사용자 승인"],
  ["limitations", "검증 범위와 향후 평가"], ["references", "용어·참고문헌·구현 대응표"],
] as const;

// 2026-11-04: 연구 출처와 구현 설명을 같은 문서에서 연결해 독자가 근거를 따라갈 수 있게 한다.
export function Research() {
  return <main className="research-page">
    <a className="brand" href="/">MAGI</a>
    <header className="research-header">
      <h1><BookOpenIcon weight="duotone" size={32} aria-hidden />연구 출처 및 적용 방식</h1>
      <p className="research-lead">작업별 루브릭을 이용한 명세 검토와 반복 개선</p>
      <p>이 보고서는 MAGI가 RubricRefine의 어떤 절차를 참고했는지, 명세 작성에 맞춰 무엇을 바꿨는지, 현재 무엇까지 확인할 수 있는지를 설명합니다.</p>
      <div className="research-source"><p lang="en"><cite>RubricRefine: Improving Tool-Use Agent Reliability with Training-Free Pre-Execution Refinement</cite></p>
        <p lang="en">Will LeVine, Brendan Raffel Evers, Sam Saltwick, Abhay Venkatesh</p>
        <dl className="research-source-meta"><div><dt>발행 연도</dt><dd>2026년</dd></div><div><dt>논문 식별자</dt><dd>arXiv:2605.09730v5</dd></div></dl>
        <a href={paper} target="_blank" rel="noreferrer">논문 원문 보기 (v5, 새 창)</a>
      </div>
    </header>

    <nav className="research-toc" aria-label="보고서 목차">
      <h2>보고서 목차</h2>
      <ol>{sections.map(([id, title]) => <li key={id}><a href={`#${id}`}>{title}</a></li>)}</ol>
    </nav>

    <section aria-labelledby="abstract"><h2 id="abstract">초록과 적용 범위</h2>
      <p>MAGI는 사용자의 요구사항을 확정한 뒤 구현 담당자에게 전달할 명세를 만들고 검토합니다. 이 과정에서 작업마다 검사 기준을 생성하고, 초안의 해당 부분을 기준별로 평가하며, 남은 결함에 관한 피드백으로 명세를 다시 작성합니다. 검토 과정의 목표를 일정하게 유지하고 가장 높은 점수를 받은 초안을 선택한다는 점에서 RubricRefine의 반복 개선 절차를 참고했습니다.</p>
      <p>평가 대상은 제품 구현 코드가 아니라 <strong>명세 문서</strong>입니다. 따라서 평가 결과는 작성된 설계와 검증 계획에 대한 판단이며, 실제 제품이 실행되거나 테스트를 통과했다는 결과가 아닙니다. 생성 모델과 평가 모델의 응답은 각각 명세와 구조화된 검토 결과를 만들고, 애플리케이션은 그 형식과 연결 관계를 검사합니다.</p>
      <p>이 보고서의 논문 결과는 원 연구의 실험을 설명합니다. MAGI에 같은 성공률이 적용된다는 뜻은 아닙니다. 현재 확인한 범위는 구현과 자동화된 계약·흐름 테스트이며, 이 방식이 실제 명세 품질을 얼마나 개선하는지는 별도의 평가가 필요합니다.</p>
    </section>

    <section aria-labelledby="background"><h2 id="background">연구 배경과 문제 정의</h2>
      <p>명세가 길어지면 요구사항이 문서 어딘가에 언급되었다는 사실만으로 충분하지 않습니다. 입력과 출력의 관계, 실패했을 때의 동작, 완료 여부를 관찰할 조건과 검증 방법이 서로 맞물려 있어야 구현자가 같은 결과를 예상할 수 있습니다. 한 문단을 추가하는 수정이 다른 섹션과 모순을 만들 수도 있습니다.</p>
      <p>검토 모델에 단순히 더 나은 문서를 요청하면 라운드마다 다른 문제를 지적하거나 이미 확정된 선택을 다시 질문할 수 있습니다. 반대로 유창한 설명이 있어도 확인해야 할 요구사항이 빠졌는지 놓칠 수 있습니다. 작업에 연결된 검사 조건과 항목별 판정은 어떤 기준으로 판단했는지, 다음 수정에서 무엇을 확인해야 하는지 기록하는 수단입니다.</p>
      <p>원 논문은 여러 도구를 조합하는 코드가 오류 없이 실행되더라도 도구 선택, 호출 형식, 값의 출처가 잘못될 수 있다는 문제를 다룹니다. MAGI에서는 같은 검토 대상을 그대로 실행하지 않고, 제품 명세에 필요한 계약과 근거를 검사하도록 질문을 바꿉니다. <a href={`${paper}#S1`} target="_blank" rel="noreferrer">논문 1절: 문제 정의</a></p>
    </section>

    <section aria-labelledby="paper"><h2 id="paper">원 논문의 방법과 실험</h2>
      <p>RubricRefine은 작업 지시와 도구 문서를 바탕으로 검사 항목을 만들고 같은 작업의 개선 라운드에서 유지합니다. 생성된 코드 후보를 항목별로 평가해 점수와 수정 피드백을 만들며, 정해진 종료 조건에 도달하면 최고점 후보를 고릅니다. 이 검토는 실제 도구 실행 전에 이뤄집니다. <a href={`${paper}#S3`} target="_blank" rel="noreferrer">논문 3절: 방법</a></p>
      <p>논문 표 1은 다단계 도구 작업인 M3ToolEval에서 일곱 모델의 평균 성공률을 RubricRefine 0.86, 고정 루브릭을 사용하는 비교 방법 0.78, 단일 생성 기준선 CodeAct 0.62로 보고합니다. 저자들은 모델·방법별로 10회 독립 시행했습니다. 이는 논문의 코드 실행 과제에서 측정한 수치이며 MAGI의 명세 품질 측정값이 아닙니다. <a href={`${paper}#S4.T1`} target="_blank" rel="noreferrer">논문 4절 표 1과 실험 설정</a></p>
      <p>논문에서는 주로 단일 단계인 API-Bank의 네 OpenAI 모델 비교에서 전체 성능 개선이 뚜렷하지 않았고, 과도하게 구체화된 기준이 일부 작업을 해칠 수 있음을 다룹니다. 또한 검사 기준이 입력 문서에 의존하므로, 잘못된 문서가 주어지면 평가도 그 오류를 따를 수 있습니다. <a href={`${paper}#S4`} target="_blank" rel="noreferrer">논문 4절: 결과와 문서 의존성</a></p>
    </section>

    <section aria-labelledby="comparison"><h2 id="comparison">논문과 MAGI의 대응 관계</h2>
      <p>두 방법은 기준을 유지하며 평가와 수정을 반복하는 제어 흐름을 공유합니다. 실제로 검사하는 산출물과 근거는 아래처럼 다릅니다. MAGI의 기준은 제품 요구사항의 인용에 연결되며 사용자 승인 흐름을 통과해야 합니다.</p>
      <div className="research-table" role="region" aria-label="논문과 MAGI 적용 비교 표 스크롤 영역" tabIndex={0}><table><caption>논문과 MAGI 적용 비교</caption><thead><tr><th scope="col">항목</th><th scope="col">RubricRefine 논문</th><th scope="col">MAGI의 명세 검토</th></tr></thead><tbody>
        <tr><th scope="row">입력 근거</th><td>작업 지시와 도구 문서</td><td>확정 요구사항, 제품 제약과 확인된 원문</td></tr>
        <tr><th scope="row">후보</th><td>실행 전 코드</td><td>요구사항에 연결된 명세 초안</td></tr>
        <tr><th scope="row">검사 분류</th><td>도구 선택·출력·호출 형식·값의 출처</td><td>요구사항·계약·데이터 흐름·실패/완료·인수 테스트</td></tr>
        <tr><th scope="row">판정과 점수</th><td>항목별 PASS/FAIL과 1–10점</td><td>PASS/FAIL/UNDETERMINED와 1–10점</td></tr>
        <tr><th scope="row">종료와 선택</th><td>최고점·정체·라운드 한도와 최고점 후보</td><td>같은 유형의 종료와 후보 선택을 명세에 적용</td></tr>
        <tr><th scope="row">결과 사용</th><td>선택된 코드를 단일 실행 대상으로 사용</td><td>선택된 명세와 남은 결함을 사용자 승인 대상으로 제시</td></tr>
      </tbody></table></div>
      <p>이 대응표는 접근 방법의 연결을 보여 줍니다. 동일한 벤치마크와 출력물에 대한 재현 실험을 뜻하지 않습니다. 논문의 상세 절차는 <a href={`${paper}#A4`} target="_blank" rel="noreferrer">부록 D: 알고리즘과 설정</a>에서 확인할 수 있습니다.</p>
    </section>

    <section aria-labelledby="generation"><h2 id="generation">작업별 루브릭 생성</h2>
      <p>MAGI는 확인된 요구사항 묶음에서 검사 기준을 만듭니다. 필수 요구사항과 제품 제약은 빠짐없이 기준에 연결해야 하며, 권장·선택 요구사항은 그 우선순위를 유지합니다. 범위 밖으로 확정된 내용도 제품의 제외 조건으로 다룹니다. 사용자가 선택하지 않은 선택 기능이 없다는 이유로 그 기능을 새 필수 동작으로 만들지 않습니다.</p>
      <p>각 기준은 해당 요구사항의 식별자와 정확히 일치하는 근거 인용을 가져야 합니다. 제공된 원문이 실제 사용자 출처와 연결될 때에는 보조 인용으로 사용할 수 있습니다. 생성된 항목에 중복 ID가 있거나 알 수 없는 요구사항을 참조하거나 인용이 해당 근거에 존재하지 않으면 유효한 루브릭으로 받아들이지 않습니다.</p>
      <div className="research-table" role="region" aria-label="루브릭 항목 구성 표 스크롤 영역" tabIndex={0}><table><caption>루브릭 항목의 구성</caption><thead><tr><th scope="col">필드</th><th scope="col">용도</th></tr></thead><tbody>
        <tr><th scope="row">rubric_id / requirement_id</th><td>기준과 그 기준이 검사하는 제품 요구사항을 식별합니다.</td></tr>
        <tr><th scope="row">condition / basis</th><td>확인할 조건과 해당 요구사항에서 발췌한 근거를 담습니다.</td></tr>
        <tr><th scope="row">sections</th><td>평가 시 확인할 명세 섹션을 지정합니다.</td></tr>
        <tr><th scope="row">category</th><td>requirement, contract, data_flow, failure_completion, acceptance_test 중 검사 영역을 나타냅니다.</td></tr>
        <tr><th scope="row">importance</th><td>core, critical, secondary 중 해당 기준의 평가 우선순위를 나타냅니다.</td></tr>
      </tbody></table></div>
      <p>검사 영역과 중요도는 서로 다른 축입니다. 예를 들어 어떤 조건이 테스트 영역에 속하는지와 그것이 점수 제한에서 얼마나 중요한지는 같은 질문이 아닙니다. 사용자의 확정 입력과 기준 생성에 사용된 근거가 유지되면 기존 루브릭을 재사용하고, 그 근거가 바뀌면 기존 평가를 현재 기준으로 간주하지 않습니다.</p>
    </section>

    <section aria-labelledby="evaluation"><h2 id="evaluation">항목별 평가와 근거</h2>
      <p>검토 단계는 일반적인 명세 결함 검토를 수행하면서 루브릭의 모든 항목을 한 번씩 평가합니다. 항목별로 <strong>충족·미충족·판단 불가로 판정</strong>하고, 어떤 명세 섹션을 확인했는지와 판단 이유를 기록합니다. 루브릭은 일반 검토를 대체하지 않으므로, 개별 항목 밖에서 발견한 구조적 모순이나 실행 가능성 문제도 검토 이슈가 될 수 있습니다.</p>
      <p>PASS에는 해당 항목이 허용한 섹션에서 실제로 존재하는 비어 있지 않은 인용이 필요합니다. FAIL은 위반이나 누락을, UNDETERMINED는 주어진 정보로 판단하기 어려운 상태를 나타냅니다. 미충족 또는 판단 불가에는 문제가 되는 문장을 인용하거나, 확인한 영역에서 필요한 조건을 찾지 못했다는 부재 근거를 기록합니다. 빈 인용을 근거로 PASS를 만들 수는 없습니다.</p>
      <p>각 비충족 판정은 같은 요구사항의 검토 이슈와 연결됩니다. 중요도가 core나 critical인 기준은 blocking 또는 major 이슈와 연결해야 하며, secondary 기준에는 minor도 허용됩니다. 여러 기준이 실제로 같은 결함을 가리키면 하나의 이슈에 연결할 수 있습니다. 이 관계가 맞지 않거나 항목이 빠진 응답은 평가 계약을 통과하지 못합니다.</p>
      <p>이 검사는 인용이 문서에 존재하는지, 연결된 ID가 서로 맞는지를 확인합니다. 문장이 존재하더라도 그 내용이 요구사항의 뜻을 충분히 만족하는지는 모델이 판단한 결과이므로, 문자열 일치만으로 의미적 정확성이나 요구사항의 완전성을 보장하지 않습니다.</p>
    </section>

    <section aria-labelledby="score"><h2 id="score">점수와 중요 실패 제한</h2>
      <p>평가 모델은 1부터 10까지의 정수 점수와 이유, 중요 실패 목록, 구체적인 수정 지시를 반환합니다. 이 점수는 모델의 순서형 판단입니다. 전체 항목 중 PASS의 비율로 자동 계산하지 않으며, 제품이 성공할 확률이나 사용자 요구를 완전히 만족할 확률을 뜻하지 않습니다.</p>
      <div className="research-table" role="region" aria-label="MAGI 점수 상한 표 스크롤 영역" tabIndex={0}><table><caption>MAGI 점수 상한</caption><thead><tr><th scope="col">확인된 상태</th><th scope="col">허용 상한</th><th scope="col">해석</th></tr></thead><tbody>
        <tr><th scope="row">core 항목 미충족 또는 판단 불가</th><td>4점</td><td>핵심 동작에 대한 기준이 충족되지 않았습니다.</td></tr>
        <tr><th scope="row">critical 항목 미충족·판단 불가 또는 blocking/major 이슈</th><td>7점</td><td>중요 계약이나 명세 결함이 남아 있습니다.</td></tr>
        <tr><th scope="row">secondary 실패 또는 minor 이슈만 남음</th><td>9점</td><td>남은 부차적 결함을 설명하고 수정할 수 있습니다.</td></tr>
        <tr><th scope="row">10점 부여의 필요조건</th><td>10점</td><td>모든 항목 PASS와 이슈 없음이 필요합니다.</td></tr>
      </tbody></table></div>
      <p>서버는 모델이 제안한 점수를 보존하고, 루브릭 판정과 이슈 및 결정적 검사에서 나온 가장 낮은 상한을 적용해 최종 점수를 정합니다. 모델이 더 높은 점수를 제안해도 상한으로 보정합니다. 중요 실패 목록도 서버가 판정과 중요 결함을 바탕으로 재구성합니다. 동일한 중요도의 UNDETERMINED에는 비충족과 같은 제한을 적용합니다.</p>
      <p>점수 보정과 별개로 응답 형식이나 평가 항목, 인용, 이슈 연결이 계약에 맞지 않으면 서버가 평가를 거부합니다. 승인할 때에는 저장된 평가와 초안이 맞는지, 점수와 중요 실패가 현재 검사 결과와 일치하는지도 다시 확인합니다. 이런 검사는 모델이 개별 조건을 의미적으로 올바르게 해석했는지까지 보증하지는 않습니다.</p>
      <p>기준의 importance는 생성 시 정해지는 검사 우선순위이고, 이슈의 severity는 실제 결함의 영향입니다. secondary 기준이라고 해서 실제로 중요한 결함을 반드시 minor로 낮추지는 않습니다. 중요 실패부터 수정 지시를 제공하되, 지시문이 확인된 요구사항을 바꾸는 근거가 되지는 않습니다.</p>
    </section>

    <section aria-labelledby="iteration"><h2 id="iteration">반복 수정과 후보 선택</h2>
      <p>한 라운드는 초안을 평가하고 결과를 해결 판단에 연결하는 단위입니다. 기본 설정은 최초 초안 평가를 포함해 최대 다섯 라운드이며, 최고점이 연속 두 번 개선되지 않으면 종료합니다. 10점을 받으면 조기 종료합니다. 수치는 설정값이며, 현재 구현의 기본값을 설명합니다.</p>
      <p>최고점 갱신은 이전 최고점보다 <strong>엄격히 높은 점수</strong>일 때만 일어납니다. 동점이나 하락은 비개선 횟수를 늘리며, 같은 최고점이 다시 나와도 먼저 얻은 후보가 유지됩니다. 다음 수정에는 기준, 직전 초안과 구조화된 검토 피드백이 전달되고, 확정 근거에 따라 해결 방법이 분류된 이슈를 반영합니다.</p>
      <pre aria-label="명세 평가와 후보 선택 의사코드"><code>{`기준 = 확정 입력에서 생성하거나 현재 기준 재사용
최고점 = 없음; 연속 비개선 = 0
반복: 최초 초안을 포함해 최대 5회 평가
  현재 초안을 기준별로 평가하고 해결 방법을 판단
  현재 점수가 최고점보다 높으면 후보 저장, 비개선 = 0
  그 밖에는 비개선 = 비개선 + 1
  미응답 제품 결정이 있으면 사용자 질문 후 답변 대기
  답변으로 확정 근거가 바뀌면 루브릭 갱신 후 새 기준으로 재평가
  10점 또는 연속 비개선 2회이면 종료
  남은 예산이 있으면 직전 피드백으로 초안 수정
종료 후 최고점 초안과 그 평가·이슈를 함께 선택`}</code></pre>
      <div className="research-example"><h3>가상의 예시: 8 → 7 → 7</h3><p>첫 초안이 8점이면 그 초안이 최고점 후보입니다. 두 번째 초안이 7점으로 내려가면 비개선 1회입니다. 세 번째도 7점이면 최고점 8점을 넘지 못했으므로 비개선 2회가 되어 종료합니다. 이때 세 번째가 아니라 첫 초안과 첫 평가가 선택됩니다. 예시의 점수와 명세는 설명을 위해 만든 가상의 예시입니다.</p></div>
      <p>동점 처리의 목적은 먼저 확보한 후보를 보존하는 데 있습니다. 점수가 같다는 사실만으로 새 초안의 다른 부분이 더 좋다고 판단하지 않습니다. 최고점 선택은 모델이 평가한 순서에 의존하므로, 기준이나 모델 판정의 오류까지 자동으로 제거하는 장치는 아닙니다.</p>
    </section>

    <section aria-labelledby="roles"><h2 id="roles">단계별 책임과 근거 우선순위</h2>
      <p>생성, 평가, 해결 판단은 서로 다른 책임을 갖습니다. 단계별 지침과 구조화 응답의 역할을 나누는 이유는 초안 작성 중 만들어진 추측이 사용자의 확정 요구사항으로 섞이거나, 평가 제안이 새로운 의무로 전환되는 것을 막기 위해서입니다.</p>
      <div className="research-table" role="region" aria-label="단계별 책임 표 스크롤 영역" tabIndex={0}><table><caption>단계별 책임</caption><thead><tr><th scope="col">단계</th><th scope="col">주요 책임</th></tr></thead><tbody>
        <tr><th scope="row">루브릭 생성</th><td>확정 요구사항에서 검사 조건과 근거를 만들고 스스로 후보를 채점하지 않습니다.</td></tr>
        <tr><th scope="row">명세 작성·수정</th><td>확정 요구사항과 해결 판단된 이슈에 따라 초안을 작성하고 기존 문서의 관련 없는 부분을 보존합니다.</td></tr>
        <tr><th scope="row">검토</th><td>일반 결함과 루브릭 항목을 평가해 근거, 이슈, 점수와 수정 제안을 만듭니다.</td></tr>
        <tr><th scope="row">해결 판단</th><td>확정 근거로 자동 보완할지, 사용자에게 빠진 제품 결정을 질문할지 분류합니다.</td></tr>
        <tr><th scope="row">계획·실행 제어</th><td>선행 조건과 라운드 상태를 확인하고 필요한 다음 단계를 선택합니다.</td></tr>
      </tbody></table></div>
      <p>확정 요구사항과 실제 사용자 출처가 우선합니다. 해결 판단된 이슈는 그 근거의 범위에서 수정 방향을 제공하고, 평가 모델의 수정 제안은 근거와 충돌할 수 없는 제안입니다. 이미 답한 제품 결정은 다시 사용하며, 새로 확인할 중대한 결정이 없는데 시스템 오류를 사용자에게 해결하도록 질문하지 않습니다.</p>
      <p>평가 점수나 수정 지시는 원문의 수치·조건을 임의로 바꿀 권한이 없습니다. 특히 권장·선택 사항을 점수 개선만을 위해 필수 기능으로 승격하지 않습니다. 반대로 중대한 선택이 실제로 미확정이라면 모델의 추정을 확정 사실로 기록하지 않고 사용자 답변을 기다립니다.</p>
    </section>

    <section aria-labelledby="storage"><h2 id="storage">보존·복구·사용자 승인</h2>
      <p>루브릭과 평가에는 각각 기준과 초안을 식별하는 해시가 연결됩니다. 각 라운드에서는 초안, 평가, 이슈와 해결 판단을 함께 저장하고 관련 추적 자료도 보존합니다. 종료 후 최고점 후보를 고를 때에는 해당 초안에 대응하는 평가와 이슈를 함께 복원합니다. 최신 초안의 평가를 이전 최고점 문서에 붙이지 않기 위한 연결입니다.</p>
      <p><code>review/rubric.json</code>은 작업에 속한 DB 문서의 이름입니다. 디스크에서 바로 찾을 수 있는 경로를 의미하지 않습니다. 화면에는 구조화된 루브릭 항목과 판정, 이유와 수정 지시가 제공되며, 검토 상태를 확인할 때 항목별 근거를 함께 살펴볼 수 있습니다.</p>
      <p>요구사항이나 확정 근거가 달라지면 이전 루브릭·평가의 유효성을 다시 확인합니다. 평가가 없거나 오래된 루브릭 등 복구 가능한 검토 상태 오류가 발생하면 사유에 따라 기준 또는 검토 단계를 다시 실행합니다. 이때 보존된 초안을 활용하며, 같은 입력·초안·오류 사유에 대한 복구는 한 번으로 제한합니다. 복구가 항상 성공하는 것은 아닙니다.</p>
      <p>실행 안전 한도로 중간에 멈춘 경우에는 저장된 실행을 이어갈 수 있습니다. 이미 선택된 최고점 후보에서 사용자가 추가 실행을 요청하면 기존 최고점은 보존하면서 새 라운드 예산과 정체 횟수로 다시 평가합니다. 미완료 모델 호출의 재실행에 동의가 필요한 경우에는 명시적 동의를 확인합니다.</p>
      <p>종료는 승인과 다릅니다. 현재 후보와 평가가 서로 맞는지 확인한 뒤 사용자에게 명세를 제시하며, 10점 미만이거나 미해결 이슈가 있다면 사용자가 그 내용을 명시적으로 수락해야 승인할 수 있습니다. 승인 요청은 사용자가 본 후보를 확인하고, 남은 결함을 수락하는 경우 평가 해시도 대조합니다. 미응답 제품 결정, 누락되거나 오래된 평가, 변경된 후보, 필수 구조 검증 실패는 수락 선택으로 우회하지 않습니다.</p>
      <p>이 처리 덕분에 평가와 문서가 서로 다른 버전으로 바뀌었는지 확인할 수 있지만, 해시는 내용의 동일성을 확인할 뿐 그 내용의 품질을 보증하지는 않습니다. 승인 이후에도 어떤 점수와 남은 결함을 수락했는지 완료 명세의 보존 정보에 연결합니다.</p>
    </section>

    <section aria-labelledby="limitations"><h2 id="limitations">검증 범위와 향후 평가</h2>
      <p>구현에는 루브릭 항목의 출처와 평가 범위, 인용의 존재, 점수 상한, 최고점 복원, 명시적 승인 경계를 검사하는 자동화 테스트가 있습니다. 이런 테스트는 예시 입력에 대해 프로그램이 정해진 계약과 제어 흐름을 지키는지 확인합니다. 테스트 통과가 실제 사용자의 모든 요구를 모델이 이해한다거나 독립 평가에서 명세 품질이 향상되었다는 뜻은 아닙니다.</p>
      <p>모델은 부정확한 기준을 만들거나, 실제 문장을 올바르게 인용하고도 그 의미를 잘못 판단할 수 있습니다. 점수가 높아도 빠진 요구사항이 원래 확정 입력에 없었다면 해당 항목 자체가 생성되지 않을 수 있습니다. 입력의 누락, 검토 모델의 편향, 작업별 비용과 지연도 별도로 다뤄야 합니다.</p>
      <p>아직 수행하지 않은 향후 평가에서는 같은 요구사항 묶음을 기준으로 루브릭 없는 검토, 고정 기준, 작업별 기준을 비교할 수 있습니다. 평가자는 모델의 점수를 보지 않은 상태에서 필수 요구 충족, 모순, 근거 타당성과 테스트 가능성을 독립적으로 채점합니다. 사용자에게 다시 물은 결정의 적절성, 잘못된 수정, 모델 호출량과 소요 시간도 함께 기록해야 합니다.</p>
      <p>비교 전에 사례 구성과 채점 기준을 정하고, 요구사항의 모호성이나 모델·작업 유형에 따라 결과를 나누어 살펴야 합니다. 이 문서에는 그 평가가 이미 수행되었거나 개선 효과가 입증되었다는 주장을 담지 않습니다. 최종 명세는 실제 요구사항과 사용 목적을 아는 사용자가 검토하고 승인해야 합니다.</p>
    </section>

    <section aria-labelledby="references"><h2 id="references">용어·참고문헌·구현 대응표</h2>
      <dl className="research-glossary"><dt>루브릭</dt><dd>작업별 요구사항에 연결된 검사 조건의 모음입니다.</dd>
        <dt>기준 중요도</dt><dd>검사 항목의 우선순위이며 실제 발견된 결함의 심각도와 구분합니다.</dd>
        <dt>판단 불가</dt><dd>근거가 부족해 충족 여부를 판단하기 어려운 항목 판정입니다.</dd>
        <dt>정체 허용 횟수</dt><dd>최고점을 개선하지 못한 평가가 연속 몇 번 발생하면 종료할지를 정하는 값입니다.</dd>
        <dt>후보 해시</dt><dd>검토·승인하려는 문서의 내용이 같은지 확인하는 식별값입니다.</dd></dl>
      <h3>참고문헌</h3><p lang="en"><cite>LeVine, W., Evers, B. R., Saltwick, S., &amp; Venkatesh, A. (2026). RubricRefine: Improving Tool-Use Agent Reliability with Training-Free Pre-Execution Refinement.</cite> arXiv:2605.09730v5.</p>
      <nav className="research-references" aria-label="원 논문 참고 링크"><a href={`${paper}#S3`} target="_blank" rel="noreferrer">논문 3절: 방법</a><a href={`${paper}#S4`} target="_blank" rel="noreferrer">4절: 실험</a><a href={`${paper}#A4`} target="_blank" rel="noreferrer">부록 D: 알고리즘</a><a href={`${paper}#A5`} target="_blank" rel="noreferrer">부록 E: 프롬프트</a></nav>
      <h3>구현 대응표</h3><p>아래 이름은 이 보고서의 설명을 코드 책임과 대조하기 위한 모듈 이름입니다. 운영 환경의 데이터 위치를 나타내지 않습니다.</p>
      <div className="research-table" role="region" aria-label="구현 대응 표 스크롤 영역" tabIndex={0}><table><caption>구현 대응표</caption><thead><tr><th scope="col">구현 모듈</th><th scope="col">담당</th></tr></thead><tbody>
        <tr><th scope="row"><code>rubric</code></th><td>기준 생성·검증, 평가 연결과 점수 상한 검증</td></tr>
        <tr><th scope="row"><code>refinement</code></th><td>라운드 기록, 최고점 추적과 초안·평가 복원</td></tr>
        <tr><th scope="row"><code>checklist_critic</code></th><td>결정적 검사와 모델의 일반·루브릭 검토 결합</td></tr>
        <tr><th scope="row"><code>review_resolution</code></th><td>확정 근거에 따른 자동 보완과 사용자 결정 분류</td></tr>
        <tr><th scope="row"><code>execution_segment</code></th><td>사용자 입력·명시적 재시도에 따른 실행 구간 상태 전환</td></tr>
      </tbody></table></div>
      <p>연구 출처와 적용 설명은 배포 코드·에셋의 라이선스 고지와 별개입니다. 오픈소스 라이선스 페이지에서 별도의 고지 내용을 확인할 수 있습니다.</p>
    </section>
    <footer className="public-links"><WorkspaceReturnLink /><a href="/licenses">오픈소스 라이선스</a><a href="/privacy">정보 처리 안내</a></footer>
  </main>;
}
