# MAGI UI 검증 환경

실제 앱의 라우터·인증 Provider·페이지·컴포넌트를 사용하고 API와 WebSocket만 브라우저 내 가짜 응답으로 바꾼다. 알 수 없는 API는 404로 실패시킨다. 검증 파일은 운영 진입점 및 빌드에 포함되지 않는다.

frontend 디렉터리에서 실행:

```powershell
node node_modules/vite/bin/vite.js --config ../tests/frontend/qa/vite.config.mts
node node_modules/typescript/bin/tsc --noEmit --project ../tests/frontend/qa/tsconfig.json
```

http://127.0.0.1:5173 에서 실제 경로를 연다. HMR은 꺼져 있으므로 소스 변경 후 다시 로드한다.

| 쿼리 | 재현 상태 |
| --- | --- |
| `role=guest`, `role=user`, `role=admin` | 로그인 / 일반 사용자 / 관리자 |
| `qa=empty`, `qa=error`, `qa=loading`, `qa=long` | 빈 결과 / 조회 실패 / 조회 대기 / 긴 제목과 32개 목록 |
| `qa=auth-loading` | 인증 연결 확인 중 |
| `qa=busy`, `qa=service-error` | 서비스 확인 중 / 서비스 조회 실패 |
| `role=guest&qa=unavailable` | 로그인 설정 미완료 |
| `status=running`, `status=error`, `status=PASS_PENDING_USER_APPROVAL`, `status=FINALIZED` | 작업 실행 / 실패 / 승인 대기 / 완료 |
| `target=implementation-package`, `target=decisions`, `target=requirement-review`, `target=impact`, `target=licenses` | `qa` 상태를 해당 API에만 적용 |

작업 ID는 `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`이며, `/jobs/<ID>` 및 `/admin/data?job_id=<ID>`로 직접 진입한다. 가짜 응답의 변경 요청도 로컬 응답만 반환한다.

과거 2026-10-25 점검의 스크린샷·측정값 저장 위치는 `.cache/ui-audit/`다. 현재 Astryx 화면의 자동 검사 출력은 아래 경로를 사용한다. `.cache/`는 로컬 산출물이므로 새 체크아웃에서는 검사를 실행해 생성한다.

## 공통 디자인 회귀 검사

QA 서버를 실행한 뒤 저장소 루트에서 아래 명령을 사용한다.

현재 세 스크립트는 Playwright의 `msedge` 채널을 지정하므로 Microsoft Edge가 필요하다. 기본 QA 주소는 `http://127.0.0.1:5173`이며, 다른 주소를 쓸 때는 `QA_BASE_URL` 환경변수로 지정한다.

```powershell
node tests/frontend/qa/design-system.mjs
node tests/frontend/qa/review-layout.mjs
node tests/frontend/qa/design-system-pages.mjs
```

첫 검사는 프레임·탭·작성창·계정 메뉴를 390·1440·1919·1920·2560px에서 확인하고 `.cache/design-system-finish/`에 캡처와 측정값을 남긴다. 두 번째 검사는 문서·검토 패널 폭, 장문·상태별 텍스트 표시, 내부 스크롤, Escape·초점 복귀를 확인한다. `viewport-960-dpr-2`는 960×540 viewport와 DPR 2를 사용하며 실제 브라우저 확대 조작을 검증하지 않는다.

| 검사 | 결과 위치 |
| --- | --- |
| `design-system.mjs` | `.cache/design-system-finish/common-ui.json`과 같은 폴더의 캡처 |
| `review-layout.mjs` | `.cache/astryx-layout/review-layout.json`과 같은 폴더의 캡처 |
| `design-system-pages.mjs` | `.cache/design-system-finish/pages/coverage.json`과 같은 폴더의 캡처 |

각 명령의 결과는 위 경로에서 확인한다.

같은 화면·상태의 전후 캡처를 검토한다.

전체 화면 검사는 25개 화면·상태를 5개 폭에서 실행하고 `.cache/design-system-finish/pages/coverage.json`에 기록한다. 전체 검사 후 `node tests/frontend/qa/design-system-pages.mjs knowledge-user admin-knowledge`처럼 이름을 지정하면 해당 화면만 다시 검사하고 기존 목록에 합친다. 항목별 캡처 시각과 실행 오류를 함께 확인한다.
