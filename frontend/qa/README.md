# MAGI UI 검증 환경

실제 앱의 라우터·인증 Provider·페이지·컴포넌트를 사용하고 API와 WebSocket만 브라우저 내 가짜 응답으로 바꾼다. 운영 서버·계정·모델은 사용하지 않는다. 알 수 없는 API는 404로 실패시킨다. 검증 파일은 운영 진입점 및 빌드에 포함되지 않는다.

frontend 디렉터리에서 실행:

```powershell
node node_modules/vite/bin/vite.js --config qa/vite.config.ts
node node_modules/typescript/bin/tsc --noEmit --project qa/tsconfig.json
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
