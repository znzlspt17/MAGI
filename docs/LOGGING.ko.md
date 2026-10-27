# 통합 로그

MAGI 관리자의 **로그** 메뉴(`/admin/logs`)에서 backend, gateway, Caddy,
PostgreSQL 운영 기록을 조회한다. 서비스·레벨·기간·메시지 문자열·추적 ID·작업 ID·실행 ID로
검색하며, 최근 15분의 최신 200건을 기본 표시한다. 메시지 검색은 대소문자를 구분한다.
상세 열기·스크롤·과거 기록 더 보기는 자동 갱신을 멈춘다.

## 구성과 보존

Python 서비스는 structlog과 orjson으로 JSON을 stderr에 출력한다.
Vector는 Docker Logs API로 대상 컨테이너를 수집하고 VictoriaLogs에 저장한다.
로그 Stack은 MAGI와 독립적으로 실행하며 저장 이력은 재배포 후에도 유지된다.
VictoriaLogs의 보관 기간은 7일이고 일 단위 파티션으로 정리한다.
용량에 따른 조기 삭제 정책은 사용하지 않는다.

Docker 자체의 `local` 로그 회전(10MiB × 3)은 유지한다. 수집 이전에 삭제되었거나
수집기 중단 중 회전·삭제된 로그는 복구할 수 없다. 수집은 best effort이며 재시도 시
중복이 발생할 수 있다. Vector 전송 버퍼는 디스크 512MiB이며 포화되면 대기한다.

상태 영역은 저장소 연결, 디스크 여유와 최근 2분 내 수집기 신호를 표시한다.
디스크 여유 20% 미만은 경고한다. 수집기 신호는 전송 경로의 동작을 나타내며
모든 컨테이너의 무손실 수집을 의미하지 않는다. 상태는 최대 30초 간격으로 갱신한다.

## Portainer 설정

먼저 `deploy/compose.logs.yaml`로 별도 로그 Stack을 배포한다.
이 Stack이 `magi-logs` 내부 네트워크를 생성한 뒤 MAGI Stack을 갱신한다.
로그 Stack은 호스트에 포트를 공개하지 않는다. MAGI Caddy가 내부 네트워크에 참여하고,
네트워크를 공유하는 gateway가 `http://victorialogs:9428`로 조회한다.

로그 Stack에 다음 비밀값 없는 설정을 지정한다.

| 설정 | 내용 |
| --- | --- |
| `LOG_CONFIG_ROOT` | `vector.yaml`을 배치한 Pi의 절대 디렉터리 |
| `LOG_DATA_ROOT` | 로그 전용 데이터 절대 디렉터리. 하위 `storage`, `buffer`를 미리 생성 |
| `MAGI_POSTGRES_CONTAINER` | 기존 PostgreSQL 컨테이너의 정확한 이름. DB 네트워크 별칭과 구분 |

`storage`는 UID/GID `10001:10001`이 쓸 수 있어야 한다. `buffer`는 Vector 실행 계정이
쓸 수 있어야 한다. 기존 PostgreSQL 데이터 경로와 공유하지 않는다.
로그 Stack의 시험 메모리 제한은 VictoriaLogs 512MiB, Vector 256MiB다.
VictoriaLogs의 128MiB 캐시 설정은 프로세스 전체 메모리 상한이 아니다.
Pi의 실제 여유 메모리와 로그 저장 디스크 여유를 확보한 뒤 적용한다.

backend·gateway·Caddy는 Compose의 `dev.magi.logs=true`와 `dev.magi.service` 라벨로
선택한다. PostgreSQL은 지정한 이름과 정확히 일치하는 컨테이너만 남긴다.
Docker 소켓은 Vector에만 제공한다. 소켓의 `ro` 마운트는 Docker API의 쓰기 권한을
차단하지 않으므로 수집기를 신뢰할 수 있는 운영 서비스로 관리한다.

두 이미지의 태그·다이제스트는 Compose에 고정되어 있다. 업데이트 시 ARM64 이미지와
설정 호환성을 함께 확인한다. MAGI 네트워크 공유 구조상 Stack 단위로 갱신한다.

## 정보 보호와 장애

입력·모델 응답·세션·인증 정보와 예외 지역변수는 애플리케이션 로그에 기록하지 않는다.
수집기는 허용한 JSON 필드만 전송하고 알려진 자격 증명 패턴을 마스킹한다.
마스킹은 임의의 원문 전체가 안전하다는 보장이 아니므로 민감한 본문을 로그에 추가하지 않는다.
Caddy 접근 로그와 PostgreSQL SQL·파라미터 로그는 활성화하지 않는다.
PostgreSQL은 SQL 부속 행과 연속 행을 제외하고, 오류 본문도 입력 리터럴 대신
레벨과 `database_ready`, `database_checkpoint`, `database_shutdown`, `postgresql_event`로 표시한다.

로그 조회 권한은 기존 MAGI 관리자 인증을 따른다. backend 전체 중단 시 관리자 인증도
불가능하므로 기존 운영 도구를 사용한다. 독립 수집된 이력은 복구 후 조회할 수 있다.
로그 Stack을 중지해도 애플리케이션은 기존 Docker 로그 출력을 계속한다.
운영 복구 시 로그 데이터 디렉터리를 삭제하지 않는다.
