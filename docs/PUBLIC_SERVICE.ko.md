# MAGI 공개 서비스 운영

Google 로그인과 PostgreSQL을 사용하는 MAGI 서비스의 설정, 배포, 관리자 기능과 데이터 관리 방법을 설명합니다. 소스 설치는 [README](../README.md#설치와-빠른-시작), 화면 사용법은 [사용자 가이드](USER_GUIDE.ko.md)를 참고하세요.

## 서비스 구성

```text
브라우저 → HTTPS 리버스 프록시 → Flask 게이트웨이 → 백엔드 → PostgreSQL
```

게이트웨이는 `127.0.0.1:5000`, 백엔드는 `127.0.0.1:8765`를 사용합니다. 게이트웨이는 loopback WebSocket으로 백엔드와 통신하며, 모델 호출과 작업 저장은 백엔드가 담당합니다. 공개 백엔드는 하나만 실행하며, 모델을 사용하는 워크플로와 부가 요청은 최대 2개까지 병렬 실행합니다.

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

백엔드 시작 시 `backend/knowledge/migrations/001.sql`부터 번호순으로 미적용 SQL을 자동 적용하고 LangGraph 공식 checkpoint 저장소를 준비합니다. 준비가 모두 끝난 뒤 요청을 받습니다. 접속 계정은 `SUPERUSER`·`BYPASSRLS` 없는 일반 서비스 계정이어야 하며, 앱 객체의 소유자로서 DDL과 조회·변경 권한이 필요합니다.

제공 backend 이미지는 서비스 프로세스를 한 번만 실행합니다. 초기화 실패나 실행 중 종료 시 오류 로그를 남기고 컨테이너를 실행 상태로 유지하며, 서비스가 응답하지 않으므로 healthcheck는 `unhealthy`가 됩니다. Portainer 콘솔에서 상태를 점검하고 원인을 해결한 뒤 backend 컨테이너를 재시작하세요. 컨테이너 중지 요청은 실행 중인 서비스에 전달됩니다. 컨테이너 자체가 강제 종료되는 경우에는 Docker 재시작 정책이 적용됩니다.

업무 자료는 `core`, 공식 실행 상태는 `workflow`, 계정·비용·사용권은 `public`에 저장됩니다. 백업·복원에는 세 스키마를 함께 포함합니다.

처음에는 관리자 계정으로 새 전용 DB에 확장과 서비스 계정 권한을 준비합니다. 아래는 DB 이름이 `vectordb`, 서비스 계정이 `app_user`인 경우입니다. 계정 생성과 인증 설정은 운영 환경에서 별도로 관리합니다.

```sql
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
GRANT CONNECT,CREATE ON DATABASE vectordb TO app_user;
GRANT USAGE,CREATE ON SCHEMA public TO app_user;
```

이후 backend를 `app_user` 연결 환경으로 시작하면 자동 설치됩니다. DB 준비용 별도 CLI는 제공하지 않습니다.

`public.schema_migrations`에는 적용 번호·파일 SHA-256·적용 시각을 기록합니다. 미적용 SQL과 이력은 하나의 트랜잭션으로 저장하며 실패하면 전체를 롤백합니다. SQL 파일은 `001.sql`, `002.sql`처럼 연속된 세 자리 번호를 사용하고, 적용한 파일을 고치거나 삭제하지 않습니다. 파일에는 명시적인 트랜잭션 제어문이나 `CREATE INDEX CONCURRENTLY` 등 트랜잭션 밖에서 실행해야 하는 구문을 넣지 않습니다. SQL은 LF 줄바꿈으로 저장합니다.

DB 버전이 코드보다 높거나 파일 번호·해시가 맞지 않으면 시작하지 않습니다. 이력 없이 MAGI 테이블이 존재해도 자동으로 적용 완료로 등록하지 않습니다. 빈 DB에서 시작해야 하며 과거 자료 전환 기능은 제공하지 않습니다. 백엔드는 프로세스 잠금을 유지해 동시 시작과 실행 중 스키마 변경을 차단합니다.

앱 SQL과 별도 연결에서 실행되는 LangGraph `setup()`은 하나의 트랜잭션이 아닙니다. checkpoint 준비 실패 시 이미 커밋된 앱 SQL 이력은 유지하고 서비스는 시작하지 않습니다. 원인을 해결한 뒤 재시작하면 앱 SQL을 중복 적용하지 않고 공식 checkpoint 준비를 재시도합니다. 라이브러리 내부 테이블은 직접 수정하지 않습니다.

로컬 임베딩 모델은 준비된 폴더를 연결하거나, 프로젝트의 embedding extra와 gateway 그룹 의존성을 설치한 Python 환경에서 준비 API를 호출합니다. 모델 준비·검색 평가용 CLI는 제공하지 않습니다.

```python
from backend.knowledge.model_files import prepare

prepare("./models/bge-m3")
```

기본적으로 최신 BGE-M3 revision을 내려받고 실제 revision과 파일 해시를 `model_revision.json`에 기록합니다. 특정 버전을 재현하려면 `prepare("./models/bge-m3", revision="<40자리 commit SHA>")`로 지정합니다. 서버 시작 시에는 이 기록을 검증하며 다운로드하지 않습니다.

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

첫 가입자에게 관리자 권한이 자동으로 부여되지 않습니다. Google 로그인 후 내 계정 메뉴에서 내부 사용자 ID를 복사합니다. 첫 관리자 지정은 backend를 중지한 상태에서 관리자 DB 연결로 아래 SQL을 실행합니다. `<내부사용자ID>`를 실제 ID로 바꿉니다.

```sql
BEGIN;
DO $$
DECLARE selected_id text := '<내부사용자ID>';
BEGIN
    IF NOT pg_try_advisory_xact_lock(72410635) THEN
        RAISE EXCEPTION 'backend를 먼저 중지하세요.';
    END IF;
    UPDATE public.users SET role='admin' WHERE id=selected_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION '사용자 ID를 확인하세요.';
    END IF;
    UPDATE public.sessions SET revoked=true WHERE user_id=selected_id;
    INSERT INTO public.admin_audit(id,actor_id,action,target_id)
    VALUES (gen_random_uuid()::text,'operator','make-admin',selected_id);
END $$;
COMMIT;
```

권한 변경 후에는 다시 로그인해야 합니다. 이후 계정·권한 관리는 관리자 화면에서 수행합니다.

관리자 화면은 `/admin`입니다. 계정·권한·사용 한도, 기록 삭제, 지식 조회·색인과 비용을 관리합니다. 마지막 활성 관리자는 강등하거나 정지할 수 없습니다. 공개 모드의 영구 기록 삭제는 관리자만 수행하며, 삭제 전 대상과 영향을 미리 확인할 수 있습니다.

계정별 일일 실행 횟수·비용 한도와 서비스 전체 비용 한도가 적용됩니다. 관리자에게도 작업별 실행 보호와 비용 상한이 적용됩니다. 실행 횟수는 접수 기준이며 시작 실패 시 자동으로 돌려주지 않습니다.

질문·승인 대기는 실행 슬롯을 점유하지 않으며 사용권 만료·연장·재획득 절차가 없습니다. 다른 사용자의 이용 여부와 관계없이 새 작업을 접수할 수 있습니다. 최대 2개가 실행되고 초과 작업은 전체 20개 상한의 대기열에서 기다립니다. 번역·변경 영향 분석은 같은 슬롯을 공유하며 슬롯이 없으면 재시도 가능한 503 응답을 반환합니다. 호출 전 비용을 예약하며, 화면의 산정 비용은 제공자 청구서와 다를 수 있습니다.

호출 후에는 일반 입력·캐시 읽기·캐시 쓰기·출력 사용량으로 비용을 산정합니다. 필요한 사용량이 누락되거나 합계가 맞지 않으면 예약액을 유지하고 확인 필요 상태로 남깁니다. 호출별 내역은 `사용량 기반 산정`, `수동 정산`, `정산 근거 불완전`을 구분합니다.

미정산 비용은 관리자 사용량 화면에서 제공자의 실제 사용량을 확인한 뒤 수동 정산합니다. 별도 비용 보정 CLI는 제공하지 않습니다.

## 지식 색인

공개 모드의 임베딩 재색인과 기록 삭제는 대기·실행 중인 작업이 없을 때 관리자 화면에서 수행합니다. 별도 재색인 CLI는 제공하지 않습니다.

## 백업과 복구

비용 산정이 미확정이어도 종료된 실행의 슬롯은 정상적으로 반환합니다. 미확정 예약액과 복구 상태는 해당 실행에만 연결되며 다른 작업을 차단하지 않습니다. 미확정 비용의 예약액은 유지되며 사용자별·서비스 전체 일일 예산에 포함됩니다. 예약을 포함한 예산이 부족하면 추가 모델 호출이 제한됩니다. 미확정 건수와 예약액은 관리자 사용량 화면에서 확인할 수 있습니다.

세 스키마를 포함한 DB를 백업하고, 모델 revision 기록과 사용 중인 이미지·설정을 보관합니다.

프로세스가 중단되거나 외부 호출 결과가 불확실해지면 운영자 복구가 필요할 수 있습니다. 이전 백엔드와 외부 호출이 모두 종료된 것을 확인한 뒤 관리자 DB 연결로 아래 SQL을 실행합니다.

```sql
BEGIN;
DO $$
BEGIN
    IF NOT pg_try_advisory_xact_lock(72410635) THEN
        RAISE EXCEPTION 'backend를 먼저 중지하세요.';
    END IF;
    UPDATE public.cost_calls SET state='uncertain' WHERE state='reserved';
    UPDATE public.execution_leases SET phase='interrupted',stopping=true
    WHERE phase IN ('queued','running','recovery');
    INSERT INTO public.admin_audit(id,actor_id,action)
    VALUES (gen_random_uuid()::text,'operator','recover');
END $$;
COMMIT;
```

이 SQL은 모델 호출을 다시 보내거나 미정산 예약을 자동 환불하지 않습니다. 관리자 화면에서 미정산 예약을 확인하고 제공자의 실제 사용량에 맞춰 정산할 수 있습니다.

002.sql은 기존 전역 사용권을 실행별 보호로 바꿉니다. backend를 중지하고 DB를 백업한 뒤 backend·gateway를 같은 버전으로 배포합니다. 중단 전 예약액은 추정 환불하지 않으며, 재시작 시 모델 호출을 자동 재개하지 않습니다. 종료 요청은 작업별로 처리하고 로그아웃은 본인 실행에만 적용됩니다.
