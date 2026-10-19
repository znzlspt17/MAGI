# MAGI Spec Engine

**개발 요청을 분석하고 검토해, AI 코딩 에이전트에 전달할 구현 명세를 만드는 도구입니다.**

요청에서 빠진 정보를 질문으로 확인하고, 요구사항과 결정의 근거를 정리한 뒤 영어 Markdown 명세를 생성합니다. 검토 과정에서 발견한 문제를 보완하고, 사용자가 승인한 문서를 최종 명세로 확정합니다. 대상 프로젝트의 코드 구현이나 코딩 에이전트 실행은 별도 단계입니다.

## 주요 기능

- **요구사항 확인:** 한국어 질문과 선택형·직접 입력 폼으로 모호한 조건을 확인합니다.
- **명세 생성과 검토:** 확정 요구사항, 설계, 데이터 흐름, 오류 처리, 인수 조건과 테스트 계획을 구조화합니다.
- **근거 추적:** 사용자 원문·답변·수정 의견과 모델의 가정을 구분하고, 요구사항과 명세 항목의 출처를 연결합니다.
- **대화 세션과 실행 이력:** 답변·수정·승인 과정을 저장하고, 완료된 세션에서도 이전 명세를 보존하며 후속 요청을 이어갑니다.
- **한국어 보기와 다운로드:** 영어 명세를 기준으로 한국어 번역을 제공하고, 선택한 언어로 문서를 다운로드합니다.
- **지식 검색과 그래프:** 저장된 요구사항·결정·명세를 권한 범위 안에서 검색하고 관계를 탐색합니다.
- **공개 서비스 운영:** Google 로그인, 사용자별 기록 격리, 관리자 화면, 실행·비용 한도와 기록 삭제 기능을 제공합니다.

## 처리 흐름

```text
개발 요청 → 인터뷰 → 요구사항 확정 → 명세 생성 → 검토·해결 판단 → 사용자 승인
               ↑                          │
               └──── 추가 질문·답변 ────────┘
```

검토에서 발견한 명세 결함은 보완하고, 사용자의 새로운 결정이 필요한 사항은 질문으로 돌려보냅니다. 이미 확정한 결정을 검토 제안만으로 바꾸지 않습니다.

| 상태 | 의미와 다음 행동 |
|---|---|
| `NEEDS_USER_INPUT` | 추가 정보나 결정이 필요합니다. 질문에 답하면 이어서 처리합니다. |
| `PASS_PENDING_USER_APPROVAL` | 검토를 통과한 후보입니다. 문서를 확인한 뒤 승인하거나 수정 의견을 보냅니다. |
| `CRITICAL_BLOCKED` | 검토·보완 후에도 필수 문제가 남았습니다. 실패 보고서를 확인합니다. |
| `FINALIZED` | 사용자 승인을 마친 최종 명세입니다. 다운로드하거나 후속 요청을 이어갈 수 있습니다. |

## 빠른 시작

### 준비 사항

- Python 3.11 이상과 [uv](https://docs.astral.sh/uv/)
- OpenAI API를 사용할 수 있는 `OPENAI_API_KEY`
- 공개 모드로 운영할 경우 PostgreSQL·pgvector와 Google OAuth 설정

저장소 루트에서 의존성을 설치합니다.

```sh
uv sync
```

API 키와 접속 비밀번호는 실행 환경에 주입합니다. 실제 값을 소스·문서·명령 예제에 넣지 않습니다. 백엔드 실행 프로그램은 저장소 루트의 `.env`도 읽지만, 이미 설정된 환경변수를 우선합니다. `.env`와 실행 산출물은 Git에서 제외됩니다.

### 로컬에서 실행하기

기본값은 로그인과 PostgreSQL이 필요한 **공개 모드**입니다. 아래 예시는 개인 개발용 로컬 모드를 두 프로세스로 실행하는 방법입니다. 인증 없는 로컬 모드는 외부에 노출하지 않습니다.

PowerShell 창 두 개를 저장소 루트에서 엽니다. API 키를 설정한 환경에서 백엔드를 먼저 실행합니다.

```powershell
$env:MAGI_PUBLIC_MODE = '0'
uv run python -m backend.server
```

다른 창에서 게이트웨이를 실행합니다.

```powershell
$env:MAGI_PUBLIC_MODE = '0'
$env:FLASK_SKIP_DOTENV = '1'
uv run python -m flask --app gateway.app:create_app run --host 127.0.0.1 --port 5000 --no-reload
```

<details>
<summary>POSIX 셸에서 실행하는 경우</summary>

백엔드와 게이트웨이를 각각 다른 터미널에서 실행합니다.

```sh
MAGI_PUBLIC_MODE=0 uv run python -m backend.server
```

```sh
MAGI_PUBLIC_MODE=0 FLASK_SKIP_DOTENV=1 uv run python -m flask --app gateway.app:create_app run --host 127.0.0.1 --port 5000 --no-reload
```

</details>

브라우저에서 [http://127.0.0.1:5000](http://127.0.0.1:5000)을 엽니다. 백엔드 주소는 기본 `ws://127.0.0.1:8765`이고, 게이트웨이는 loopback 주소로만 연결합니다.

1. 새 세션에서 만들고 싶은 기능과 조건을 입력합니다.
2. 요구사항 확인 질문에 답합니다.
3. 생성된 명세와 검토 항목을 확인하고 필요한 수정 의견을 보냅니다.
4. 검토를 통과한 후보를 승인한 뒤 최종 문서를 다운로드합니다.

DB 설정이 전혀 없는 로컬 모드에서는 파일로 저장합니다. DB를 설정하면 저장소 연결을 사용하며, 연결 실패 시 파일 모드로 조용히 전환하지 않습니다. 실행 중 환경변수나 소스를 바꿨다면 백엔드와 게이트웨이를 모두 재시작합니다.

### 공개 서비스로 운영하기

공개 모드에서는 Google 로그인 후 사용자별 세션을 사용합니다. 서버의 독점 사용권과 일일 실행·비용 한도를 적용하고, 관리자 화면에서 계정·지식·기록 정리·비용을 관리합니다.

| 설정 | 용도 |
|---|---|
| `MAGI_PUBLIC_MODE` | 기본 `1`. 위 로컬 실행 예시에서는 `0`을 명시합니다. |
| `MAGI_PUBLIC_ORIGIN` | 공개 HTTPS origin입니다. |
| `GOOGLE_OAUTH_ID`, `GOOGLE_OAUTH_SECRET` | Google OAuth 웹 클라이언트 설정입니다. |
| `MAGI_SUBJECT_PEPPER` | 계정 식별자에 사용하는 서버 비밀값입니다. |
| `MAGI_DB_*` | PostgreSQL 접속 설정입니다. |
| `MAGI_INTERNAL_KEY` | 선택 설정입니다. 사용하면 백엔드와 게이트웨이에 같은 값을 주입합니다. |

공개 서비스 DB 계정에는 `SUPERUSER`·`BYPASSRLS` 권한을 허용하지 않습니다. 첫 가입자가 자동으로 관리자가 되지 않으며, 운영 명령으로 관리자 권한을 부여합니다.

Flask 개발 서버 대신 운영 WSGI 서버와 HTTPS 리버스 프록시를 사용합니다. OAuth 콜백, DB 권한, 프록시, 관리자 설정과 복구 명령은 [공개 서비스 운영 가이드](docs/PUBLIC_SERVICE.ko.md)를 참고하세요.

## 모델과 언어

생성·검토·컴파일·번역은 **OpenAI `gpt-6-luna`**를 사용합니다.

질문과 검토 설명은 한국어, 기준 명세와 정규화된 요구사항은 영어로 작성합니다. 사용자 원문, 명시적인 인용문, 코드, 경로와 식별자는 보존합니다. 한국어 번역은 요구사항 ID·수치·코드 보존을 검증하고 문서별로 캐시합니다.

세션별로 대화 문맥을 유지하며, 작업의 입력·출력 토큰 사용량을 기록합니다.

## 지식 저장과 로컬 임베딩

PostgreSQL과 pgvector를 사용해 작업 상태, 단계별 문서, 결정과 근거의 관계를 저장합니다. 지식 그래프에서는 원본 문서를 열고 연결된 요구사항·결정·명세를 탐색할 수 있습니다.

DB 필수 설정은 `MAGI_DB_HOST`, `MAGI_DB_NAME`, `MAGI_DB_USER`, `MAGI_DB_PASSWORD`입니다. 포트는 기본 `5432`, `MAGI_DB_SSLMODE`는 기본 `prefer`이며, TLS 없는 로컬 DB는 `disable`을 사용합니다. 전용 DB의 `vector` 확장은 관리자가 먼저 활성화해야 하고, 앱의 스키마 마이그레이션은 백엔드 시작 시 적용됩니다.

의미 검색은 **로컬 BGE-M3 모델**을 사용합니다. 모델이 준비되지 않은 자료는 텍스트 검색으로 조회할 수 있으며, 유료 임베딩 API로 자동 전환하지 않습니다.

```sh
uv sync --extra embedding
uv run python -m backend.knowledge.prepare_model --output ./models/bge-m3
```

준비한 폴더를 `MAGI_EMBEDDING_MODEL_PATH`에 지정하고 `MAGI_EMBEDDING_DEVICE=cpu`로 설정합니다. 다운로드는 준비 명령에서 명시적으로 수행하며, 서비스 시작 시에는 모델을 다운로드하지 않습니다.

긴 문서의 검색 결과는 원본별로 묶어 보여주며, 검색한 내용에서 원본 문서를 열어 확인할 수 있습니다.

공개 모드의 재색인은 관리자 운영 작업으로 실행합니다. 독립 명령을 사용할 때는 백엔드를 정상 종료한 뒤 같은 OS 계정으로 실행합니다.

```sh
uv run python -m backend.knowledge reindex
```

기존 파일 기록 이관과 검색·그래프 사용법은 [사용자 가이드](docs/USER_GUIDE.ko.md)를 참고하세요.

## 저장과 장애 처리

기본 작업 폴더는 `magi_web_data/`입니다. `MAGI_DATA_DIR`로 변경할 수 있습니다. DB 사용 시 DB의 커밋된 기록을 기준으로 로컬 산출물을 복원합니다.

| 경로 | 주요 내용 |
|---|---|
| `raw/`, `analysis/` | 사용자 입력, 인터뷰 결과와 확정 요구사항 |
| `review/` | 검토 이슈와 해결 판단 |
| `draft/` | 영어 초안과 승인 후보 |
| `final/FINAL_AGENT_SPEC.md` | 사용자 승인을 마친 최종 명세 |
| `critical/` | 보완 실패 보고서와 관련 문서 |
| `completed/`, `history/` | 이전 완료본과 실행 시점의 문서 |
| `state/`, `translations/` | 재개 상태, 실행 이력, 사용량과 번역 캐시 |

실패한 작업의 입력과 기록은 보존됩니다. 외부 호출 결과가 불확실하면 중복 실행하지 않고 관리자 복구가 필요한 상태로 남깁니다.

기록 삭제는 미리보기와 확인을 거치며, DB 데이터·관계·벡터와 로컬 파일을 함께 정리합니다. 공개 모드의 영구 삭제는 관리자 권한이 필요합니다. 상세 복구 절차는 [운영 가이드](docs/PUBLIC_SERVICE.ko.md#관리자와-장애-복구)를 참고하세요.

## 소스 구조와 Python API

```text
frontend/   HTML·CSS·JavaScript 작업 공간
gateway/    Flask HTTP API와 브라우저 이벤트 중계
backend/    명세 엔진·파이프라인·모델 호출·저장·작업 서버
protocol/   공통 통신 규약과 진단 유틸리티
```

브라우저는 게이트웨이와 통신하고, 게이트웨이는 loopback WebSocket으로 백엔드에 요청합니다. 모델 호출과 상태 저장은 백엔드가 담당합니다. 프런트엔드에는 별도 빌드 단계가 없습니다.

Python에서 직접 사용하는 진입점은 `MagiSpecEngine`입니다. 기존 `magi_spec` 패키지와 `magi-spec` CLI는 현재 지원하지 않습니다.

```python
from backend import MagiSpecEngine

engine = MagiSpecEngine()
result = engine.generate_from_text(
    text="사용자가 메모를 작성하고 검색할 수 있는 앱을 만들어 주세요.",
    output_dir="./magi_output",
    web_search_mode="off",
)
print(result.status)

# 질문·수정 처리를 마치고 승인 대기 상태가 되면 명세를 확인한 뒤 실행합니다.
# engine.approve("./magi_output")
```

`generate_from_file`, `answer`, `revise`, `approve`, `status`도 제공합니다. 설정은 `MagiConfig` 또는 `MagiConfig.from_file()`에 전달한 YAML·JSON으로 구성합니다. Python API는 웹 계정·사용권·일일 비용 제한을 적용하는 공개 서비스 경로와 구분됩니다.

## 사용 시 알아둘 점

- 재시작한 작업 서버는 저장된 기록을 복원하지만, 중단된 모델 작업을 자동으로 재실행하지 않습니다.
- 대화 연결이나 현재 요구사항 계약을 복구할 수 없는 과거 세션은 새 작업을 생성해야 할 수 있습니다. 기록을 자동으로 변환하거나 삭제하지 않습니다.
- 반드시 본인의 OPENAI API키가 필요합니다. 없으면 동작하지 않습니다.

## 상세 문서

- [사용자 가이드](docs/USER_GUIDE.ko.md): 화면 사용법, 질문·수정·승인, 지식 검색과 기록 이관
- [공개 서비스 운영](docs/PUBLIC_SERVICE.ko.md): 로그인, DB 권한, 배포, 관리자와 비용·장애 복구
