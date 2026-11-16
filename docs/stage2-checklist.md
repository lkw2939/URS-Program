# 2단계 — 직원 계정·프로젝트·원본 PDF 보관

시작 지시: 1단계 근거를 제시한 뒤 사용자가 “진행”을 지시했다. 이를 다음 개발 착수 허용으로 기록한다. 사용자가 시험 자료를 직접 전부 검토했다거나 실제 고객 문서를 승인했다고 간주하지 않는다. 개발 단계에서 매번 별도의 확인을 반복 요구하지 않고, 명시한 필수 시험을 실행해 결과를 기록한다. 업무 단계와 최종 문서 승인의 게이트는 유지한다.

모든 항목 필수. 최초 상태 UNVERIFIED. 대상 구현 버전 stage2-v1. 공통 명령: `python -m unittest discover -s tests -v`. 근거: tests/test_workspace.py 및 실행 로그. 검토 실행자: 개발 에이전트(사람의 업무 승인 아님).

| ID | 요구사항 | 구현/입력 | 기대 결과 |
|---|---|---|---|
| S2-01 | G1 | 서버 내부 계정 생성, 정상/잘못된 비밀번호 | 비밀번호 해시 저장, 정상 로그인만 허용, 세션 만료/로그아웃 후 접근 차단 |
| S2-02 | G1 G2 | 다른 직원의 프로젝트·PDF ID로 접근 | 목록에서 숨김, 다운로드/업로드 모두 거부 |
| S2-03 | G2 | 프로젝트 생성 후 DB 재연결 | 프로젝트와 소유자·원본 기록 복원 |
| S2-04 | A1 | 정상 PDF 업로드·다운로드 | 원본 바이트와 SHA-256 일치, 별도 저장, 기존 파일 덮어쓰기 없음 |
| S2-05 | A1 | 비PDF·손상 PDF·암호화 PDF·크기 초과·경로형 파일명 | 거부 또는 안전한 이름 처리, 원본 처리와 추출 완료를 구분 |
| S2-06 | C5 C6 G2 | 업로드 후 업무 단계 조회 및 후속 실행 요청 | 원본 무결성 검사만 통과, 추출 이후 미구현 단계와 승인 차단 |
| S2-07 | G1 A1 | 실제 HTTP 로그인→프로젝트→업로드→다운로드→로그아웃 | 인증/CSRF 통제 및 원본 일치 확인 |
| S2-08 | G2 | 직원용 웹 화면 | 로그인·프로젝트·파일 업로드·원본 다운로드 제공, 미구현 상태 명확 표시 |

이 단계는 원본 파일 보관을 검증한다. 모든 본문·표·그림의 추출 보존(A1 전체/A2~A4)은 3단계에서 검증한다. 사내 외부 배포, 회사 SSO, 공동 프로젝트 권한 관리 및 실제 고객 PDF 평가는 이 단계의 완료 주장에 포함하지 않는다.

## 실행 결과

S2-01~S2-08 모두 아래 명시한 시험 범위에서 PASS.

| 항목 | 실제 검증 근거 |
|---|---|
| S2-01 | `test_password_hash_sessions_logout_expiry`, `test_login_rate_limit_and_password_policy`: scrypt 해시·세션 해시, 오인증 거부, 만료·로그아웃, 5회 실패 제한 |
| S2-02 | `test_owner_isolation_and_restart`, HTTP 시험: 직원 간 프로젝트·문서 조회/원본 다운로드/처리/업로드 차단 |
| S2-03 | `test_owner_isolation_and_restart`: SQLite 재연결 후 프로젝트·문서 메타데이터 복원 |
| S2-04 | `test_original_bytes_immutable_and_not_overwritten`: 동일 이름 중복 업로드 분리, 원본 바이트·SHA-256 일치, SQL UPDATE/DELETE 차단 |
| S2-05 | `test_invalid_encrypted_oversize_empty_pdf_rejected`: 비PDF·손상 샘플·암호화·빈 문서·제한 초과 거부. 경로형 이름은 표시 메타데이터로만 취급 |
| S2-06 | `test_only_original_integrity_passes_and_downstream_blocks`: 원본 무결성만 PASS, 추출 검사기 미구현은 NOT_IMPLEMENTED, 번역 실행과 최종 승인 차단 |
| S2-07 | `test_http_login_upload_download_csrf_and_other_user`: 실제 HTTP 왕복, CSRF·외부 Origin·수동 PASS 거부, 원본 다운로드 및 로그아웃 후 접근 거부 |
| S2-08 | `tests/browser_smoke.py`: 실제 Chromium 로그인·프로젝트 생성·PDF 등록·상태 표시·다운로드 바이트 비교·새로고침·로그아웃. 1360px/390px 화면 캡처와 모바일 가로 넘침 검사, pageerror 0건 |

전체 단위·HTTP 통합시험 23개 통과, 실패 0, 건너뜀 0. 깨끗한 `.venv`에 `pypdf==6.10.0` 설치 후 재실행해 통과했다. 브라우저 흐름 1개도 통과했다.

로그: [stage2-tests.txt](evidence/stage2-tests.txt), [stage2-browser.txt](evidence/stage2-browser.txt).
화면 근거: [데스크톱](evidence/stage2-desktop.png), [모바일](evidence/stage2-mobile.png).

검증 데이터는 시험용으로 생성한 PDF와 임시 계정이다. 실제 고객 URS의 번역·기술 분석 품질 또는 사내 배포 완료를 의미하지 않는다. PDF 파서의 구조 인식은 지원 범위를 확인하는 검사이며 모든 손상·특수 PDF의 완전한 판독을 보장하지 않는다. 직원별 단독 프로젝트 접근을 제공하며 공유 권한은 아직 제공하지 않는다. 원본 백업·복구 운영 및 회사 계정 연동은 별도 배포 검토가 필요하다.

## 다음 단계

3단계는 PDF 전체 페이지·텍스트·표·시각자료·좌표 추출과 누락 검토다. 지금은 원본 보관까지만 구현했으며 전체 내용 추출을 PASS로 처리하지 않는다. 실제 직원 업무의 원본 검증과 이후 단계 전환은 서버의 문서별 상태로 계속 통제한다.
