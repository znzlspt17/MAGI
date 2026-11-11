# MAGI UI 검증 환경

실제 앱의 라우터·인증 Provider·페이지·컴포넌트를 사용하고 API와 WebSocket만 브라우저 내 가짜 응답으로 바꾼다. 운영 서버·계정·모델은 사용하지 않는다. 알 수 없는 API는 404로 실패시킨다. 검증 파일은 운영 진입점 및 빌드에 포함되지 않는다.

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

작업 ID는 `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`이며, `/jobs/<ID>` 및 `/admin/data?job_id=<ID>`로 직접 진입한다. 가짜 응답의 변경 요청도 로컬 응답만 반환한다. ZIP 다운로드 전송 자체와 실제 서비스 상태는 이 환경에서 검증하지 않는다.

스크린샷·화면 폭별 측정 결과는 저장소 루트의 `.cache/ui-audit/`에 저장했다.

## 공통 디자인 회귀 검사

QA 서버를 실행한 뒤 저장소 루트에서 아래 명령을 사용한다.

```powershell
node tests/frontend/qa/design-system.mjs
node tests/frontend/qa/review-layout.mjs
node tests/frontend/qa/design-system-pages.mjs
```

첫 검사는 프레임·탭·작성창·계정 메뉴를 390·1440·1919·1920·2560px에서 확인하고 `.cache/design-system-finish/`에 캡처와 측정값을 남긴다. 두 번째 검사는 문서·검토 패널 폭, 장문·상태별 텍스트 표시, 내부 스크롤, Escape·초점 복귀를 확인한다. `zoom-equivalent-200`은 실제 브라우저 확대 조작과 구분하는 동등 viewport·배율 검사다.

픽셀 넘침 검사가 통과해도 시각적 마감이 완료된 것으로 간주하지 않는다. `docs/MAGI_DESIGN_SYSTEM.ko.md`에 따라 사용자 제보 이미지와 같은 화면·상태의 전후 캡처를 직접 검토한다.

전체 화면 검사는 25개 화면·상태를 5개 폭에서 실행하고 `.cache/design-system-finish/pages/coverage.json`에 기록한다. 전체 검사 후 `node tests/frontend/qa/design-system-pages.mjs knowledge-user admin-knowledge`처럼 이름을 지정하면 해당 화면만 다시 검사하고 기존 목록에 합친다. 항목별 캡처 시각과 실행 오류를 함께 확인한다.
