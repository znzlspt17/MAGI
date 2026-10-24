# MAGI 공개 서비스 운영

Google 로그인과 PostgreSQL을 사용하는 MAGI 서비스의 설정, 배포, 관리자 기능과 데이터 관리 방법을 설명합니다. 소스 설치는 [README](../README.md#설치와-빠른-시작), 화면 사용법은 [사용자 가이드](USER_GUIDE.ko.md)를 참고하세요.

## 서비스 구성

```text
브라우저 → HTTPS 리버스 프록시 → Flask 게이트웨이 → 백엔드 → PostgreSQL
```

게이트웨이는 `127.0.0.1:5000`, 백엔드는 `127.0.0.1:8765`를 사용합니다. 게이트웨이는 loopback WebSocket으로 백엔드와 통신하며, 모델 호출과 작업 저장은 백엔드가 담당합니다. 공개 백엔드는 하나만 실행합니다.

소스에서 직접 설치할 때는 화면을 미리 빌드해야 합니다. 제공되는 컨테이너 이미지에는 빌드된 화면이 포함됩니다.

## 환경 변수

| 변수 | 적용 대상 | 값과 용도 |
|---|---|---|
| `OPENAI_API_KEY` | 백엔드 | 명세 생성·검토·번역에 사용할 API 키 |
| `PUBLIC_MODE` | 양쪽 | 웹 서비스는 `1` |
| `LOCAL_LOGIN` | 양쪽 | 기본 `0`. localhost Google 로그인은 `1` |
| `PUBLIC_ORIGIN` | 양쪽 | 경로·끝 슬래시 없는 공개 HTTPS origin |
| `PROXY_HOPS` | 게이트웨이 | 기본 `0`. 신뢰할 프록시 수 |
| `SERVER_URL` | 게이트웨이 | 기본 `ws://127.0.0.1:8765` |
| `GOOGLE_OAUTH_ID`, `GOOGLE_OAUTH_SECRET` | 백엔드 | Google OAuth 웹 클라이언트 설정 |
| `SUBJECT_PEPPER` | 백엔드 | 계정 식별자 처리용 비밀값. 기존 계정 연결을 위해 같은 값을 유지 |
| `INTERNAL_KEY` | 양쪽 | 내부 통신 인증 키. 사용할 경우 양쪽에 같은 값 지정. 제공 컨테이너 구성에서는 필수 |
| `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | 백엔드 | PostgreSQL 접속 설정 |
| `DB_PORT` | 백엔드 | 기본 `5432` |
| `DB_SSLMODE` | 백엔드 | 기본 `prefer`. TLS 없는 DB는 `disable` |
| `EMBEDDING_MODEL_PATH` | 백엔드 | 준비된 로컬 BGE-M3 모델 폴더 |
| `EMBEDDING_DEVICE` | 백엔드 | `cpu` |
| `CONTAINER` | 양쪽 | 제공 이미지가 `1`로 설정하는 컨테이너 실행 표시 |

### 설정 적용 방식

백엔드·게이트웨이·관리 명령은 실행 환경에 주입한 설정만 사용합니다. 인증값을 명령행 인자로 전달하거나 Git에 저장하지 않습니다.

실제 인증값은 실행 환경에서 관리합니다. 모델은 `gpt-6-luna`로 고정되며 모델·가격을 선택하는 환경변수는 없습니다.

## PostgreSQL과 모델 준비

공개 모드에는 PostgreSQL과 pgvector가 필요합니다. 전용 DB에서 `vector` 확장을 활성화하고, DB 접속·스키마 사용과 앱 객체의 조회·변경 권한이 있는 서비스 계정을 사용합니다. 서비스 계정은 `SUPERUSER`나 `BYPASSRLS` 권한을 가질 수 없습니다.

스키마 설치·갱신은 관리자 명령으로 수행합니다. 서버 시작과 작업 실행은 DDL을 수행하지 않습니다. 서비스 계정은 생성 권한 없이 준비된 객체의 조회·변경 권한으로 실행합니다.

업무 자료는 `core`, 공식 실행 상태는 `workflow`, 계정·비용·사용권은 `public`에 저장됩니다. 백업·복원에는 세 스키마를 함께 포함합니다.

새 DB에서 `vector` 확장을 준비한 뒤, 관리 연결 환경을 주입한 터미널에서 실행합니다. 서비스 역할은 `app_user`입니다.

```sh
uv run python -m backend.knowledge install
uv run python -m backend.knowledge verify --application-role app_user
```

기존 DB를 이번 버전으로 전환할 때는 다음 순서로 진행합니다.

1. 복구 가능한 DB 백업과 현재 이미지 태그를 확보하고 backend·gateway를 중지합니다. PostgreSQL과 Caddy는 유지할 수 있습니다.
2. 새 backend 이미지의 일회성 관리 컨테이너에서 같은 DB 네트워크와 관리자 연결 환경을 주입해 `python -m backend.knowledge migrate`를 실행합니다. 원본 업무 테이블은 보존하며 인증 자료와 비용 원장은 복제하지 않습니다.
3. `python -m backend.knowledge verify --application-role app_user`로 내용·참조·소유권·checkpoint를 검증하고 활성화합니다. 예상하지 못한 자료나 원본 변경이 발견되면 중단합니다.
4. 프런트엔드를 포함한 gateway와 backend를 같은 버전으로 교체하고 시작합니다. 작업 조회·질문 답변·승인·명시적 재개를 확인합니다. 시작만으로 모델 호출을 재개하지 않습니다.
5. 이전 업무 테이블의 제거는 백업과 운영 확인 후 별도 승인 단계로 수행합니다. 이 명령들은 이전 테이블을 삭제하지 않습니다.

전환 검증 동안 보존한 `public` 업무 원본은 새 서비스의 조회·수정·삭제 대상이 아닙니다. 검증 기간의 접근과 보존 책임을 운영자가 관리하고, 운영 전환 확인과 백업 검증 후 별도 승인으로 폐기합니다. 계정·비용·사용권 테이블은 이 폐기 대상에 포함하지 않습니다.

전환 중 실패하면 서비스를 중지한 상태로 같은 명령을 재실행합니다. 복구는 전환 전 DB 백업과 이전 서비스 이미지를 함께 복원하는 방식으로 수행합니다. 새 버전에서 사용자 작업을 받기 시작한 뒤에는 추가 입력 보존과 정합성을 별도로 확인해야 합니다.

로컬 임베딩 모델은 다음 명령으로 준비합니다.

```sh
uv sync --extra embedding --group gateway
uv run python -m backend.knowledge.prepare_model --output ./models/bge-m3
```

기본적으로 최신 BGE-M3 revision을 내려받고 실제 revision과 파일 해시를 `model_revision.json`에 기록합니다. 특정 버전을 재현하려면 `--revision <40자리-commit-SHA>`를 지정할 수 있습니다.

준비된 폴더를 `EMBEDDING_MODEL_PATH`에 지정합니다. 서비스 시작 시 모델을 자동 다운로드하지 않습니다. 제공 컨테이너에서는 모델을 외부 폴더에서 읽기 전용으로 마운트합니다.

## Google 로그인

Google Cloud의 웹 애플리케이션용 OAuth 클라이언트에서 다음 리디렉션 URI를 등록합니다.

```text
https://<공개-도메인>/auth/google/callback
```

`PUBLIC_ORIGIN`은 `https://<공개-도메인>`으로 지정하고 `GOOGLE_OAUTH_ID`·`GOOGLE_OAUTH_SECRET`을 백엔드에 주입합니다. OAuth 동의 화면이 테스트 상태라면 로그인할 계정을 테스트 사용자로 등록해야 합니다.

계정 연결에는 검증된 Google 식별자를 사용합니다. 이름·이메일·사진을 사용자 데이터로 저장하지 않으며, 관리자 지정에도 이메일 대신 MAGI의 내부 사용자 ID를 사용합니다.

### localhost 로그인

개인 PC에서 Google 로그인을 사용할 때는 `http://localhost:5000/auth/google/callback`을 OAuth 리디렉션 URI로 등록합니다. 양쪽 프로세스에 다음 설정을 적용합니다.

```powershell
$env:PUBLIC_MODE = '1'
$env:LOCAL_LOGIN = '1'
$env:PUBLIC_ORIGIN = 'http://localhost:5000'
$env:PROXY_HOPS = '0'
```

이 구성에도 DB·OAuth·계정 식별자 설정이 필요합니다. 저장소 루트에서 백엔드를 실행합니다.

```powershell
uv run python -m backend.server
```

같은 설정을 주입한 다른 터미널에서 게이트웨이를 실행합니다.

```powershell
$env:FLASK_SKIP_DOTENV = '1'
uv run python -m flask --app gateway.app:create_app run --host 127.0.0.1 --port 5000 --no-reload
```

브라우저 주소는 `http://localhost:5000`을 사용합니다. 공개 배포는 `LOCAL_LOGIN=0`과 HTTPS origin을 사용합니다.

## Linux에서 직접 실행

화면 빌드가 완료된 소스에서 운영용 의존성을 설치합니다. 로컬 임베딩을 사용하면 `--extra embedding`도 함께 지정합니다.

```sh
uv sync --locked --group gateway
uv run python -m backend.server
```

환경변수를 주입한 별도 프로세스에서 게이트웨이를 실행합니다.

```sh
uv run gunicorn --workers 1 --threads 16 --bind 127.0.0.1:5000 "gateway.app:create_app()"
```

HTTPS 리버스 프록시는 원래 Host와 Origin을 유지하고, 게이트웨이의 `PROXY_HOPS`를 실제 프록시 수에 맞춥니다. 게이트웨이·백엔드 포트는 외부에 직접 공개하지 않습니다. 긴 문서 요청과 WebSocket 연결을 처리할 수 있도록 프록시 대기 시간을 설정합니다.

## Raspberry Pi와 Portainer

제공되는 `deploy/compose.portainer.yaml`은 ARM64용 Caddy·백엔드·게이트웨이 구성입니다. 기존 PostgreSQL에 외부 네트워크 `magi-db`로 연결하며, Caddy와 앱이 네트워크 공간을 공유합니다.

GitHub Actions의 **Build Raspberry Pi release** 워크플로로 기본 브랜치의 이미지를 GHCR에 게시할 수 있습니다. Portainer Stack에 다음 이미지 변수를 설정합니다.

```dotenv
BACKEND_IMAGE=ghcr.io/znzlspt17/magi-backend:latest
GATEWAY_IMAGE=ghcr.io/znzlspt17/magi-gateway:latest
CADDY_IMAGE=ghcr.io/znzlspt17/magi-caddy:latest
```

Stack에서 입력받는 나머지 변수는 다음과 같습니다.

| 변수 | 값과 용도 |
|---|---|
| `PUBLIC_ORIGIN` | 공개 HTTPS origin |
| `OPENAI_API_KEY`, `GOOGLE_OAUTH_ID`, `GOOGLE_OAUTH_SECRET` | 모델·로그인 인증 설정 |
| `SUBJECT_PEPPER`, `INTERNAL_KEY` | 기존 계정 식별·내부 인증 설정 |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD` | 기존 전용 DB와 서비스 계정 |
| `DB_SSLMODE` | Compose 기본값 `disable` |
| `DEPLOY_ROOT` | Pi의 배포 폴더 절대 경로 |
| `MODEL_ROOT` | 준비된 BGE-M3 모델 폴더 절대 경로 |
| `HTTP_PORT`, `HTTPS_PORT` | 호스트 포트. 기본 `8080`·`443` |

`DEPLOY_ROOT` 아래에는 `Caddyfile`, `caddy-data/`, `caddy-config/`가 있어야 합니다. DB 호스트는 같은 외부 네트워크에서 `magi-postgres`라는 이름으로 접근할 수 있어야 합니다.

다음 항목은 현재 Compose의 고정값입니다. Stack 환경변수에 같은 이름을 입력해도 이 값이 바뀌지는 않으며, 변경하려면 Compose 설정을 수정해야 합니다.

| 대상 | 고정 설정 |
|---|---|
| 양쪽 앱 | `PUBLIC_MODE=1`, `LOCAL_LOGIN=0` |
| 게이트웨이 | `PROXY_HOPS=1`, `SERVER_URL=ws://127.0.0.1:8765` |
| 백엔드 DB | `DB_HOST=magi-postgres`, `DB_PORT=5432` |
| 백엔드 저장·모델 | `EMBEDDING_MODEL_PATH=/models/bge-m3`, `EMBEDDING_DEVICE=cpu` |
| 모든 서비스 | `TZ=Asia/Seoul` |

이미지는 컨테이너 실행 표시, Python 실행 설정과 모델 오프라인 설정을 포함합니다. 모델 파일은 이미지에 포함되지 않습니다.

이미지를 갱신할 때는 실행 중인 작업을 마치고 DB를 백업한 뒤 Stack 전체를 갱신합니다. `latest` 이미지 게시만으로 기존 컨테이너가 자동 갱신되지는 않습니다.

## 관리자와 비용 관리

첫 가입자에게 관리자 권한이 자동으로 부여되지 않습니다. Google 로그인 후 내 계정 메뉴에서 내부 사용자 ID를 복사하고, 백엔드를 중지한 상태에서 DB 설정이 주입된 운영 터미널로 관리자 지정 명령을 실행합니다.

```sh
uv run python -m backend.access make-admin --user-id <내부사용자ID>
```

사용자 목록은 `uv run python -m backend.access users`로 확인할 수 있습니다. 권한 변경 후에는 다시 로그인해야 합니다.

관리자 화면은 `/admin`입니다. 계정·권한·사용 한도, 기록 삭제, 지식 조회·색인과 비용을 관리합니다. 마지막 활성 관리자는 강등하거나 정지할 수 없습니다. 공개 모드의 영구 기록 삭제는 관리자만 수행하며, 삭제 전 대상과 영향을 미리 확인할 수 있습니다.

계정별 일일 실행 횟수·비용 한도와 서비스 전체 비용 한도가 적용됩니다. 관리자에게도 실행 독점과 비용 상한이 적용됩니다. 실행 횟수는 접수 기준이며 시작 실패 시 자동으로 돌려주지 않습니다.

질문·승인 대기의 사용권은 3분 뒤 만료됩니다. 모델 실행·번역·저장 중에는 이 대기 만료를 적용하지 않습니다. 호출 전 비용을 예약하며, 화면의 산정 비용은 제공자 청구서와 다를 수 있습니다.

호출 후에는 일반 입력·캐시 읽기·캐시 쓰기·출력 사용량으로 비용을 산정합니다. 필요한 사용량이 누락되거나 합계가 맞지 않으면 예약액을 유지하고 확인 필요 상태로 남깁니다. 호출별 내역은 `사용량 기반 산정`, `이전 보수적 산정`, `수동 정산`을 구분합니다.

기존 자동 산정 기록의 보정은 백엔드를 중지하고 DB 설정이 주입된 운영 터미널에서 수행합니다. 기본 동작은 미리보기이며, 작업 ID 또는 시작일·종료일로 범위를 지정합니다. 기간은 관리자 화면과 같은 한국 시간의 호출일 기준입니다.

```sh
uv run python -m backend.access reprice-costs --job-id <작업ID>
uv run python -m backend.access reprice-costs --start 2026-10-21 --end 2026-10-22
uv run python -m backend.access reprice-costs --job-id <작업ID> --apply
```

`--apply`는 원장과 일일 사용액을 함께 보정하고 이전·이후 금액을 감사 기록에 남깁니다. 수동 정산, 미확정 기록, 지원되지 않는 계산 정책, 사용량 근거가 부족한 기록은 제외합니다. 과거 캐시 쓰기 사용량이 없는 기록은 추정해서 변경하지 않습니다. 결과의 `eligible`·`applied`·`excluded`는 각각 보정 대상·적용·제외 건수이며, `rows`에 건별 사유가 포함됩니다.

## 지식 색인

공개 모드의 임베딩 재색인은 다른 작업이 실행 중이지 않을 때 관리자 화면에서 수행합니다. 독립 명령은 백엔드를 중지한 상태에서 같은 OS 계정으로 실행합니다.

```sh
uv run python -m backend.knowledge reindex
```

## 백업과 복구

비용 산정이 미확정이어도 종료된 실행의 사용권은 정상적으로 반환합니다. 질문·승인 대기는 기존 대기 시간을 적용합니다. 미확정 비용의 예약액은 유지되며 사용자별·서비스 전체 일일 예산에 포함됩니다. 예약을 포함한 예산이 부족하면 추가 모델 호출이 제한됩니다. 미확정 건수와 예약액은 관리자 사용량 화면에서 확인할 수 있습니다.

세 스키마를 포함한 DB를 백업하고, 모델 revision 기록과 사용 중인 이미지·설정을 보관합니다.

프로세스가 중단되거나 외부 호출 결과가 불확실해지면 운영자 복구가 필요할 수 있습니다. 이전 백엔드와 외부 호출이 종료된 상태에서 DB 환경변수를 주입해 다음 명령을 실행합니다.

```sh
uv run python -m backend.access recover --confirm-stopped
```

복구 명령은 모델 호출을 다시 보내거나 미정산 예약을 자동 환불하지 않습니다. 관리자 화면에서 미정산 예약을 확인하고 제공자의 실제 사용량에 맞춰 정산할 수 있습니다.
