# MAGI 전체 화면 UI/UX 점검

검증일: 2026-10-25. 기존 React·Tailwind CSS·shadcn/ui·Radix·Phosphor 리소스와 보라색 톤을 유지했다. Cytoscape·D3 그래프와 Recharts 차트도 기존 컴포넌트를 사용했다.

## 검증 방법과 범위

`frontend/qa/`에서 실제 앱 라우터와 컴포넌트를 실행하고, API·WebSocket만 브라우저 내 가짜 응답으로 대체했다. 관리자 기능, 승인, 생성 등의 검증 요청은 운영 서버나 모델로 전송하지 않았다. 알 수 없는 API는 404로 실패시킨다.

기본 페이지와 아래 하위 화면을 실제로 열어 1440·768·390·320px 폭에서 캡처했다. 모바일 사이드바는 모바일 폭에서 별도로 확인했다. 정상 화면 외에도 해당 기능의 로딩·빈 결과·오류, 긴 요청, 32개 작업 목록, 실행·실패·승인·완료 상태를 재현했다. 320px에서는 문서 전체 너비와 뷰포트 너비를 비교했다. 긴 표·코드·그래프 상세의 내부 스크롤은 허용했다.

현재 캡처와 측정값은 저장소의 `.cache/ui-audit/`에 있다. `coverage.json`은 최종 캡처 목록, `layout.json`은 측정 기록이다. 스크린샷은 Git에 추가하지 않았다. 재현 명령과 쿼리는 `frontend/qa/README.md`에 있다.

## 화면별 결과

아래의 **확인**은 로컬 재현 환경에서 화면을 열고 배치·상태를 확인했다는 뜻이다. 운영 기능 전체의 성공이나 실기기 접근성 인증을 뜻하지 않는다. 캡처 이름의 `after-<이름>-<폭>.png` 형식으로 해당 화면을 찾을 수 있다.

| 순서 | 화면·동작 | 발견 사항과 처리 | 재검증 | 캡처 이름 |
| --- | --- | --- | --- | --- |
| 1 | 로그인 | 정상적인 401을 오류로 표시하던 문제 수정, 제목·여백 축소 | 정상·설정 미완료 확인 | login, login-disabled |
| 2 | 최초 연결 | 인증 로딩 안내 유지 | 확인 | auth-loading |
| 3 | 사이드바·검색 | 간격 정리, 검색 결과가 없다는 안내 추가 | 모바일 열기·검색·닫기 확인 | mobile-sidebar, sidebar-filter-empty |
| 4 | 계정 메뉴 | 기존 ID·권한·운영 링크와 메뉴 유지 | 데스크톱·모바일 확인 | account-menu |
| 5 | 서비스 상태 | 정상 상태의 큰 카드 축소, 입력 영역의 중복 오류 안내 제거 | 확인 중·실패·비활성 확인 | service-busy, service-error |
| 6 | 개인정보 안내 | 제목·모서리·공개 페이지 여백 일관화, 본문 유지 | 확인 | privacy |
| 7 | 라이선스 | 제목·항목 간격 정리, 원문·다운로드 링크 유지 | 원문 펼침·로딩·오류 확인 | licenses, license-expanded, licenses-loading, licenses-error |
| 8 | 새 요청 | 중복 소개 문구 제거, 프로젝트 선택 카드·입력창 축소 | 정상·빈 프로젝트·조회 오류 확인 | home, home-empty, home-error |
| 9 | 프로젝트 생성 | 기존 모달과 폼 유지, 기본 문단 여백 정리 | 입력·Escape 닫기 확인 | project-dialog |
| 10 | 등록된 공통 결정 | 접힌 영역의 불필요한 카드 제거, 항목 패딩 축소 | 정상·빈 결과·오류·로딩 확인 | decisions, decisions-empty, decisions-error, decisions-loading |
| 11 | 결정 출처 | 출처 인용·전체 식별값 유지 | 팝오버 확인 | decision-source |
| 12 | 재사용 결정 | 대화 위에서 펼쳐도 대화 영역을 전부 밀어내지 않도록 높이 제한 | 펼침 확인 | reused-decisions |
| 13 | 승인본 결정 등록 | 기존 등록 확인과 출처 확인 유지 | 후보·등록 확인 모달 확인 | decision-candidates, decision-registration |
| 14 | 질문과 답변 | 선택 카드·질문 간격 축소 | 라디오·체크박스·추천 이유 확인 | conversation, question-selection, question-guidance |
| 15 | 의견 입력 | 질문 답변 중에는 추가 입력창을 접어 대화 공간 확보 | 키보드 펼침·초안 보존 확인 | feedback-composer |
| 16 | 확대 편집 | 기존 자동 확장·최대 높이·별도 편집 유지 | 닫은 뒤 원래 입력창 포커스 확인 | expanded-editor, input-growth |
| 17 | 작업 상태 | 상태별 기존 안내·승인·재시도 유지 | 실행·실패·승인 대기·승인 전송·완료 확인 | conversation-running, retry, approval, approval-sent, conversation-completed |
| 18 | 명세 읽기 | 옆의 큰 안내 카드를 짧은 가로 영역으로 변경. 근거표와 변경 검토는 필요할 때 펼치고 본문 공간 확보 | 문서·언어·원문 전환 확인 | document, document-raw |
| 19 | 요구사항 검토 | 문서 모드에서는 접고, 근거 전용 모드에서는 전체 표시 유지 | 표·모바일 카드·빈 결과·오류·로딩 확인 | requirement-review, review-empty, review-error, review-loading |
| 20 | 근거 인용·전체 보기 | 기존 팝오버·인라인 펼침 유지 | 확인 | evidence-popover, evidence-expanded |
| 21 | 변경 검토 | 제목·본문·목록 여백 축소, 문서에서 별도로 펼침 | 원문 비교 펼침 확인 | change-review |
| 22 | 완료 명세 선택 | 완료본 선택·다운로드 도구를 한 영역으로 접어 정리 | 이전·보존된 완료본 열기 확인 | completed-documents |
| 23 | 실행 이력 | 실행별·하위 단계별 펼침 유지 | 확인 | history, execution-steps |
| 24 | 연구 기록 | 검색 링크와 원문 검토의 구분 유지 | 연구 단계 열기 확인 | research |
| 25 | ZIP 모달 | 브라우저 기본 문단 여백이 파일 목록을 불필요하게 키우는 문제 수정 | 파일·전체 해시·빈 상태·오류·로딩 확인 | package, package-hashes, package-empty, package-error, package-loading |
| 26 | 사용자 지식 검색 | 버튼·검색·필터 밀도와 선택 색상 일관화 | 그래프·목록 확인 | knowledge-user, knowledge-list |
| 27 | 그래프 상세 | 좁은 화면의 상세와 목록 겹침 방지, 상태색은 유지 | 요구사항·명세·결정 확인 | impact, knowledge-spec-detail, knowledge-decision-detail |
| 28 | 그래프 필터·설정 | 선택·강조 색상을 보라색 계열로 통일 | 필터·간격·라벨·배치 설정 확인 | graph-filters, graph-settings |
| 29 | 영향 검토 | 입력 최소 높이·섹션 간격 축소 | 분석 결과·관계 경로·빈 결과·오류·로딩 확인 | impact-analysis, impact-path, impact-empty, impact-error, impact-loading |
| 30 | 관리자 운영 현황 | 헤더·카드 밀도와 상태색 일관화, 실행 ID 줄바꿈 | 확인 | overview |
| 31 | 사용자 편집 | 화면별 폼 겹침 수정. 데스크톱 그리드, 태블릿 2열, 좁은 화면 1열. 빈 결과·로딩·오류 재조회 추가 | 확인 | users, users-empty, users-error, users-loading |
| 32 | 작업·데이터 | 목록·필터·상세 헤더 패딩 축소 | 표·모바일 카드·빈 결과·오류·로딩·긴 내용 확인 | data, jobs-empty, jobs-error, jobs-loading, jobs-long |
| 33 | 작업 상세 | 헤더·본문 여백 축소, 기존 초점 복귀 유지 | 요약·최종 명세·초안·보완 보고서·처리 이력 5개 탭 확인 | detail-요약, detail-최종 명세, detail-초안, detail-critical-filled, detail-처리 이력, detail-history-expanded |
| 34 | 작업 삭제 확인 | 기존 대상·경고·취소·확인 경로 유지 | 미리보기 모달만 확인, 삭제 실행 안 함 | before-cleanup-dialog |
| 35 | 관리자 그래프·프로젝트 삭제 | 사용자 화면과 색상·밀도 통일 | 그래프·프로젝트 변경·삭제 확인 모달 확인 | knowledge-admin, project-delete |
| 36 | 비용·관측 기준 | 필터·카드·표 밀도 정리. 320px 날짜 잘림·저장 버튼 돌출 수정 | 비용·호출·토큰 차트, 작업별·사용자별·호출별 내역, 일별 수치·정산 폼 확인 | costs, cost-chart-*, cost-rows-*, cost-daily, cost-settlement |
| 37 | 관리자 접근 제한 | 기존 권한 안내 유지 | 일반 사용자 거부 화면 확인 | admin-denied |

## 동작 검증과 결과

- 입력창은 한 줄 약 40px에서 긴 입력 약 160px까지 확장되는 것을 브라우저에서 측정했다.
- 확대 편집을 Escape로 닫으면 `request-text`로, 모바일 메뉴를 닫으면 메뉴 버튼으로 포커스가 돌아오는 것을 확인했다.
- 질문 선택·추가 의견 펼침·등록 모달·문서 언어/Markdown·이력·차트·내역 탭을 실제로 조작했다. 초안 보존과 중복 제출·지연 응답 처리 등은 기존 및 추가 회귀 테스트로 확인했다.
- 1440·768·390·320px의 측정 기록에서 페이지 전체 가로 넘침은 발견되지 않았다. 표와 코드의 내부 가로 스크롤은 의도된 동작이다.
- 터치 환경에는 최소 44px 조작 영역과 모바일 입력 16px 규칙을 적용했다. 브라우저 폭 변경은 실기기의 터치·가상 키보드 검증을 대신하지 않는다.
- 프런트엔드 24개 테스트 파일, 116개 테스트 통과. 라이선스 검사 2개 통과. 운영 코드와 QA 진입점 타입 검사, 프로덕션 빌드 통과. 번들 크기 경고는 남아 있다.

## 전후 비교와 한계

후속 확인: 사용자가 지적한 사이드바와 본문 사이의 회색 막대는 `SidebarRail`의 기본 버튼 배경이었다. 최초 육안 점검에서 놓친 항목이며, 레일의 배경·padding·appearance를 초기화했다. 브라우저에서 투명 배경과 접기·펼치기 동작을 확인했다. 캡처: `.cache/ui-audit/sidebar-rail-fixed.png`.

요청 첫 화면의 같은 데이터·같은 폭 전후 비교는 `.cache/ui-audit/comparison-home.png`에 있다. 전체 화면 캡처의 전후 기준은 이번 점검 시작 시점과 수정 후다. 앞선 공통 CSS 축소도 이미 시작 시점에 포함되어 있다. 일부 상세 화면은 테스트 데이터에 완료본·재사용 결정을 추가해 확인했으므로 전후 픽셀 비교 대상으로 사용하지 않았다.

운영 배포, 실제 Google 인증, 실제 모델 호출·결제·정산, 실제 데이터 삭제와 ZIP 파일 전송, 모바일 실기기의 가상 키보드는 검증하지 않았다. 화면과 테스트 결과만으로 WCAG 전체 준수나 운영 데이터의 모든 조합을 보증하지 않는다. 다른 작업에서 동시에 변경 중인 업무 로직과 안내 문구는 보존했으며, 이 점검의 UI 개선으로 간주하지 않았다.
