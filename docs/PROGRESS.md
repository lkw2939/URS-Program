# 실제 API/HTML 진단 명령 추가 (2026-11-16)

`python scripts/check_api_report.py`는 같은 서버의 .env 로딩 규칙 및 현재 직원/최근 PDF의 저장 프롬프트 유무·모델 설정·기존 호출 기록을 읽습니다. API 키, 프롬프트/PDF/HTML 본문은 출력하지 않습니다.
`--call`을 붙이면 저장 프롬프트/PDF/API 설정이 있는 경우에만 생산용 report 코드와 실제 OpenAI 어댑터로 최대 1회 호출합니다. 호출 비용은 기존 문서별 한도/사용량 원장에 기록합니다. 실제 응답 모델/effort/HTTP 상태/usage를 기록하며, 생성 결과는 새 비공개 진단 디렉터리에만 보관합니다. 기존 보고서와 단계 결과는 변경하지 않습니다.
현재 코드에는 reasoning.effort 지정이 없습니다. 실제 기본 effort는 공급자가 응답에서 반환하지 않으면 미확인으로 남깁니다. 모델은 기존 URS_OPENAI_MODEL을 그대로 사용합니다.
검증: 모의 단위시험 4개 추가(미저장 프롬프트 호출 차단, 모델/effort 조회, 성공 HTML 주소 외 동일, 401 실패). 실제 사용자 서버의 API 호출 성공은 아직 확인되지 않았으며, 합성 시험 결과로 대체하지 않습니다.

---

# 기본 실행 방식 복구 (2026-11-16)

사용자 요청: 기존 Codespaces 사용을 계속하며, 이전 안내로 바뀐 실행 방식부터 복구합니다.
- start.py의 기본 백그라운드 실행을 제거하고 원래의 전경 서버 실행으로 복구했습니다.
- 실행 시 기존 감독 프로세스를 먼저 종료하며, 오래된 자동 시작 hook은 중지 표시로 비활성화합니다. devcontainer의 postStartCommand도 제거했습니다.
- 기존 원본/계정/세션/DB/HTML 보고서를 유지합니다. 다른 PC로 이전하거나 보고서를 재생성하지 않습니다.
- 새 복구 회귀시험: 실제 백그라운드 종료, 전경 CLI 인자, 동일 DB 경로, 원본 검증기록/로그인 세션 보존. 전체 현재 시험은 93개입니다.
- 현재 사용자 브라우저의 외부 404 원인은 미확인입니다. 로컬/모의/Chromium 통과를 외부 접속 성공으로 보고하지 않습니다.
- 실제 Codespaces는 현재 연결에서 접근 권한 403으로 원격 갱신할 수 없습니다. 같은 Codespaces에서 git pull && python start.py로 적용합니다.

---

# 백그라운드 웹 실행 추가 (2026-11-16)

- Linux/Codespaces의 `python start.py`는 첫 계정 설정 후 분리된 서비스 감독 프로세스를 실행합니다.
- 터미널 종료 후 유지, 서버 오류 종료 시 자동 재시작, 중복 실행 방지, `service.py stop/start/status`, 수동 종료 상태 유지.
- Codespaces postStartCommand로 환경 시작 때 재실행합니다. 계정이 없으면 자동 계정을 만들지 않습니다.
- 현재 자동시험 92개(새 서비스 시험 4개 포함), Chromium 및 HTML 재열기. 서비스 시험은 임시 DB/로컬 포트/실제 프로세스에서 확인합니다.
- Codespace 자체의 절전/정지 중에는 웹이 유지되지 않습니다. 실제 Codespaces 재개 시험은 미실행이며 외부 상시 호스팅을 개설하지 않았습니다.
- 기존 운영 DB/보고서/키 설정 변경 및 유료 API 호출 없음. 적용 안내: GITHUB-START.md.

---

# 원본 PDF → 모델 HTML 보고서 변경 (2026-11-16)

현재 동작은 이 문서 상단 및 docs/direct-html-report.md를 따릅니다. 과거 텍스트 추출/블록 번역/Word·PDF 제작 시험 결과는 이 변경의 검증 근거가 아닙니다. 변경 전 문서는 docs/history/before-direct-html-*.md에 보존했습니다.

| 항목 | 현재 상태 | 근거 |
|---|---|---|
| 텍스트 추출 전용 코드/API/UI/단계 삭제 | PASS | 추출 모듈·검토 API·블록 번역·자동 우회 경로 삭제, HTTP/브라우저 시험 |
| 원본 PDF + 프롬프트 원문 전달 | PASS (모의 응답) | input_file + 저장한 input_text + 이미지 연결 안내. SYSTEM/용어집/고정 서식 없음 |
| HTML 원본 보존 / 이미지 주소만 변경 | PASS | 원본 UTF-8 보존, HTML 재직렬화 없음, 주소 바깥 문자열 비교 |
| 한 페이지 여러 그림 / 도면 | PASS (합성 PDF) | 서로 다른 빨강/파랑 원본 영역 및 벡터 도형, 역순 자리 연결 |
| 독립 검증·기술 분석 별도 유지 | PASS (모의 응답) | 원본 PDF와 원본 HTML 대조, 보고서 수정 없음 |
| 기존 DB 기록·문서 보존 | PASS (임시 DB) | 시작/설정 저장 시 재생성 없음, 과거 artifacts/results/events/approvals/definitions 행 보존 |
| 전체 현재 시험 | PASS | 단위/HTTP 88개, 실제 Chromium 데스크톱/모바일, HTML/PNG 재열기 |
| 실제 OpenAI/고객 품질/99%/직원 인수 | UNVERIFIED / 보류 | 이번 작업은 유료 API 호출 0회, 실제 고객 문서/운영 DB 접근 없음 |

재현: `python scripts/validate.py`. 최신 근거: docs/evidence/validation-summary.json, final-tests.txt, final-browser.txt, final-html.txt, html-comparison.json.
