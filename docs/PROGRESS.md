# HTML 저장 PASS / 문서 끝 열람 불일치 점검 (2026-11-17)

| 항목 | 상태 |
|---|---|
| 저장 PASS와 열람 차단이 동시에 발생하는 조건 | 확인: 생성은 HTML 시작 표지, 열람은 절대 끝의 닫는 html 태그 검사 |
| 완료 표시와 열람 상태 정합성 | 수정: 읽기 미확인 현재 파일은 저장됨·끝 확인 필요, 완료 수에서 제외 |
| 원본/최종/응답 기록 읽기 전용 점검 ZIP | 구현 / 소유자 권한·원본 바이트 보존 시험 |
| 실제 25쪽 고객 HTML 끝부분·이번 API 상태 | 미확인: 운영 DB/직원 세션 접근 없음 |
| 태그 보정 / 재생성 / 운영 파일 덮어쓰기 / 유료 호출 | 없음 |

스크린샷의 28개 이미지 연결 PASS는 저장/연결 성공이며 본문 완전성을 증명하지 않습니다. 기존 read_final은 html 닫는 태그 뒤에 코드블록 표시가 있어도 차단합니다. 이 경우와 실제 본문 중단을 구분하기 위해 파일을 수정하지 않고 원문을 수집합니다. 태그 추가·코드펜스 제거·정규화·역사 PASS/DB 수정 없이 보존합니다.

문서 카드/검토 화면은 현재 리비전이 읽기 가능한 결과가 아닐 때 “저장됨 · 끝 확인 필요”로 표시합니다. 과거 읽기 가능한 결과가 있으면 기존처럼 이전 보고서로 열며 최신 결과로 표시하지 않습니다. 저장 파일이 있는데 불완전 판정이면 “저장된 HTML은 있으나 문서 끝·완전성 확인이 필요합니다”로 표시하여 결과가 없다는 안내와 구분합니다.

“저장 HTML·응답 기록 내려받기 (완전성 미확인)”는 인증된 문서 소유자만 GET stored-review.zip?revision=R로 받습니다. ZIP은 원본 PDF(source.original.pdf), 실제 저장 report.raw.html 및 report.html 바이트, comparison.json을 포함합니다. comparison은 각 파일의 마지막4000자/크기/해시, html·body 끝 태그 유무, 마지막 html 태그 뒤 문자열, 이미지 연결 외 동일성/변경 개수, 생성 설정 기록, 해당 리비전의 저장 API 시도를 담습니다. 파일 본문은 이 비공개 점검 산출물에만 포함하고 로그·공개 저장소에는 넣지 않습니다. 상태가 없으면 빈 기록이며 추정하지 않습니다. API completed나 태그 유무만으로 원본 PDF 내용 누락 여부를 판정하지 않습니다.

수정 전후 저장 바이트와 DB 전체 기록 동일성, 닫는 태그+후행 코드펜스, 실제 중단된 본문, 다른 직원 접근 차단, UI 완료/열람 정합성, ZIP 다운로드와 원문 바이트를 시험합니다. 총 단위/HTTP148개 및 Chromium/HTML 검사 결과는 docs/evidence/validation-summary.json 기준입니다. 스크린샷 saved-html-end-check.png는 합성 자료로 실제 고객 결과가 아닙니다.

실제 고객 문서의 판단은 적용 후 기존 저장 점검 ZIP을 받아 같은 원본의 마지막 내용과 대조해야 합니다. 유료 재생성은 필요하지 않습니다. 기존 API 응답 기록이 없다면 미확인으로 남깁니다.

---

# 보고서 API 대기시간 / 비동기 웹 접수 / 안전한 실패 기록 (2026-11-17)

| 항목 | 상태 |
|---|---|
| 기존 90초 경로 확인 | report→OpenAI→urlopen의 소켓 I/O 대기 제한. 브라우저 fetch에 별도 타이머 없음 |
| 보고서 API 대기시간 조정 | 보고서 전용 기본600초, 웹 직원별 버전 저장10~3600초, 환경변수 선택 지원 |
| 긴 웹 연결 제거 | 웹 버튼은 202 접수 후 1.5초 간격 상태 조회. 동시 접수는 진행 중 작업 재사용 |
| 출력 한도·프롬프트·이미지·검토 입력 유지 | 기존 설정 전달 유지, 모의 브라우저 실제 요청16000/900초 확인 |
| 원인별 기록 / 기존 HTML 보존 | 임시 DB·모의 HTTP 시험, 운영/유료 호출0회 |
| 실제 25쪽 생성 / 실제 Codespaces 적용 | 미실행 / 별도 확인 필요 |

보고서 전용 대기시간 우선순위는 웹 report_timeouts 최신값 > URS_OPENAI_REPORT_TIMEOUT_SECONDS > 600초입니다. 기존 ai_settings 출력 토큰/모델/effort 및 보고서 프롬프트는 수정하거나 덮어쓰지 않습니다. 독립검증·기술분석의 기존90초 호출은 유지합니다. urllib timeout은 소켓 연결/읽기 대기 제한이며 전체 작업의 절대 실행시간 상한이 아닙니다.

웹 생성 버튼은 background:true로 접수하고 완료까지 조회합니다. 자동 유료 재시도는 없습니다. 웹 새로고침은 같은 서버의 실행 중 작업 조회만 재개합니다. 서버 재시작 등으로 메모리 작업 상태가 사라지면 완료/실패를 추정하거나 다시 생성하지 않고 기존 기록 확인을 안내합니다. 진단의 waiting_response는 완료 기록을 못 받은 상태이며 실제 공급자 처리 여부는 미확인입니다.

검증 기록 JSON의 record.api_diagnostics와 report FAIL evidence.api_diagnostics에서 call_id/revision/max_output_tokens/timeout_seconds/elapsed_seconds/http_status/response_status/incomplete_reason/outcome/error_type을 봅니다. elapsed_scope=api_exchange, timeout_kind=socket_io. 보고서 작업 전체 시간은 기존 시작/결과 이벤트로 대조합니다. outcome은 timeout_before_response, timeout_reading_response, http_error, connection_error, response_parse_error, response_read_error, max_output_tokens, incomplete_response, html_processing_error, completed로 구분합니다. 없는 HTTP/응답 정보는 null이며 API 키·원본·프롬프트·모델 본문·예외 메시지는 진단에 기록하지 않습니다. 과거 실패의 사라진 값은 복원/추정하지 않습니다.

report_diagnostics는 시도별 추가 기록입니다. 기존 report HTML/프롬프트/설정/결과는 덮어쓰지 않습니다. 검증 JSON에 새 시도가 추가되면 기록 전체 해시는 바뀝니다. 기존 진단 CLI도 API 호출 시 원장과 이 진단에 새 행을 기록하므로 읽기 전용 명령이 아닙니다.

전체 단위/HTTP145개와 기존/대기시간/저장 HTML 브라우저·HTML 재열기를 검증합니다. 현재 시험은 실제 고객 PDF가 아닌 fixture입니다. 브라우저에서 로그인→출력16000 저장→대기900초 저장→보고서 버튼→202→생산용OpenAI 어댑터→모의 HTTP를 검사했습니다. 정상 저장, 응답 전/중 타임아웃, HTTP429, 불완전 응답, JSON오류, HTML오류, 이미지 연결 예외, 기존 리비전 보존, 비밀 비기록을 시험합니다. 설정 저장 자체는 API를 호출하지 않습니다.

적용: git pull && python start.py. 웹의 “보고서 OpenAI 응답 대기시간 (초)”에서 변경합니다. 이 명령으로 보고서를 생성하지는 않습니다. 운영 사용자 API/DB 접근이나 유료 호출은 이번 작업에 없습니다.

---

# 저장된 HTML 열람 / 이전 리비전 복구 (2026-11-17)

| 항목 | 상태 |
|---|---|
| 현재 리비전 파일 기반 HTML 확인 | 구현 / 임시 DB·Chromium 시험 통과 |
| 실패한 새 생성 뒤 이전 리비전 열람·다운로드 | 구현 / 이전 표시·revision 고정·양쪽 bytes 일치 시험 |
| 결과 없음 / 실패 이유 / 불완전·변조 파일 안내 | 구현 / 임시 DB 시험 |
| 원본·보고서·설정·결과·이벤트의 읽기 전용 보존 | 임시 DB 전체 행 전후 비교 통과 |
| 사용자 운영 문서의 실제 저장 여부 | 미확인: 직원 세션/운영 DB 접근 없음 |
| 유료 API 호출 | 0회 |

원인: 기존 화면은 현재 report-metadata 유무만으로 결과 영역을 숨겼습니다. 새 리비전 실패 시 이전 파일이 있어도 열람 경로가 사라졌습니다. 이번 변경은 stage 승인/생성 조건을 해제하지 않고 파일 열람 버튼을 별도로 둡니다.

`detail.reports`는 원본 소유권 확인 후 저장 report.html을 리비전별로 읽기만 합니다. 현재 정상 파일이 있으면 HTML 확인, 과거 파일만 있으면 이전 보고서 보기, 없으면 “아직 열 수 있는 완성 HTML이 없습니다”를 표시합니다. 과거 결과는 현재 승인에 사용하지 않습니다. 원본·최종본·사진 자산·해시가 있으면 기존 바이트 동일성과 치환 무결성을 확인하고, 메타데이터가 없는 복구 파일은 “무결성 메타데이터 미기록”으로 구분합니다. 출력 한도 기록이 없으면 기본 5000을 추정 표시하지 않습니다.

파일의 HTML 문서 끝이 없거나 기록된 해시가 맞지 않으면 완성 결과로 열지 않고 원인을 보여줍니다. 이는 번역 품질/내용 완전성 인증이 아닙니다. 기존 파일을 보정/덮어쓰거나 보고서를 재생성하지 않습니다.

운영자 읽기 전용 확인: `python scripts/inspect_saved_html.py` (또는 --document ID). sqlite mode=ro/query_only로 기존 DB를 읽으며 Workspace 초기화, AI 요청, DB 수정, 프롬프트/본문/API 키 출력이 없습니다. 문서별 현재/이전/없음, 사용 가능한 리비전 및 생성 실패 이유를 출력합니다. 실제 운영 확인이 되기 전까지 “이 문서에 완성 HTML이 있었다”고 보고하지 않습니다.

검증: tests/test_saved_reports.py 11개, 기존 처리 시험 12개, tests/browser_saved_reports.py의 현재/이전/없음/양쪽 다운로드. 전체 단위/HTTP 132개 및 기존/저장 HTML Chromium·HTML 재열기를 검증합니다. 최신 결과·소스 해시는 docs/evidence/validation-summary.json 기준. 스크린샷 docs/evidence/saved-html-*.png는 고객 자료가 아닌 합성 fixture입니다.

---

# 실행 유지·재시작 경로 통일 (2026-11-17)

| 항목 | 상태 |
|---|---|
| Linux/Codespaces 기본 실행을 동일 서비스 경로로 통일 | 구현 / 임시 DB 실제 프로세스 시험 |
| 터미널 종료 후 유지, 중복 시작 방지, 기존 전경 서버 이관 | 실제 프로세스 시험 통과 |
| 서버 종료 / HTTP 무응답 3회 후 자식 서버 복구 | SIGTERM / SIGSTOP 주입 시험 통과 |
| 명시적 수동 종료 상태 / 계정·원본·세션 유지 | 임시 DB 시험 통과 |
| 유료 API·실제 고객 품질 | 이번 작업 미실행 |
| 사용자 Codespaces 504 / 외부 URL 정상 접속 | 미확인, 해결 완료로 판정하지 않음 |

`start.py`의 POSIX 경로는 동일 Service.restart를 사용합니다. 서비스의 start/stop/restart를 제어 잠금으로 직렬화하고, 시작 완료는 해당 서비스의 리스닝 PID와 실제 HTTP 200을 함께 확인합니다. 헬스체크는 프록시를 거치지 않고 루프백에 직접 요청합니다. Codespaces postStartCommand는 수동 종료 플래그를 존중하는 autostart입니다. 기존 Codespace에 postStartCommand 적용은 컨테이너 설정 반영이 별도로 필요합니다.

수동 실행: `git pull && python start.py`. 종료: `python service.py stop`. 재시작: `python service.py restart`. 프로세스 유지 기능은 Codespace 자체 정지/절전 중에는 동작하지 않습니다. 유료 API 요청 재실행이나 기존 보고서 재생성은 하지 않습니다. 운영 DB/키 접근 없음.

집중 시험: 서비스 수명주기 12개. 전체 최신 검사 결과와 소스 해시는 docs/evidence/validation-summary.json을 기준으로 합니다. 이전 전경 실행 안내는 이 항목으로 대체합니다.

---

# 8795 포트 중복 실행 복구 (2026-11-17)

- 사용자 로그의 `OSError: [Errno 98] Address already in use`를 기존 전경 URS 서버로 재현했습니다. 이전 실행기는 감독 프로세스만 중지해 전경 서버가 남았고, 종료하지 않아도 종료 메시지를 표시했습니다.
- 이제 같은 사용자·프로젝트 경로·DB 경로·URS 실행 명령·리스닝 소켓을 확인한 기존 서버만 종료한 뒤 다시 실행합니다. 다른 프로그램/다른 DB/식별 불가 프로세스는 자동 종료하지 않습니다. 중복 시작 명령은 잠금으로 차단합니다.
- 새 프로세스의 로컬 HTTP 200 및 URS 화면 식별자를 확인한 뒤에만 실행 확인 메시지와 브라우저 열기를 진행합니다. 종료 대상이 없으면 없다고 표시합니다.
- 재시작 시험에서 원본 검증 해시와 기존 로그인 세션 보존을 확인했습니다. 기존 운영 데이터 접근·보고서 재생성·유료 API 호출은 없습니다.
- 현재 단위/HTTP 118개, Chromium 및 HTML 재열기 결과는 docs/evidence/validation-summary.json에 기록합니다. 합성 PDF/임시 DB/모의 AI 시험이며 사용자 Codespaces 외부 접속 성공을 뜻하지 않습니다.
- 적용: `git pull && python start.py`. 로컬 HTTP 응답 확인 메시지를 확인하고 터미널을 유지합니다. 설정 UI 위치: 로그인 → 프로젝트 작업실 → AI 호출 설정.

---

# 웹 모델·effort·출력 한도 설정 UI (2026-11-17)

- 로그인 후 프로젝트 작업실에 AI 호출 설정 폼을 추가했습니다. 모델 ID, effort 선택, 출력 한도 직접 입력/16K·32K·64K·128K 빠른 선택을 저장합니다.
- 직원별 버전 저장이며 다음 호출부터 즉시 적용합니다. 기존 보고서/원본/프롬프트/검증 기록과 진행 중인 요청은 유지합니다. API 키는 UI/설정 응답에 노출하지 않습니다.
- 5,000 고정값을 제거하고 API max_output_tokens와 비용 예약에 실제 저장한 한도를 사용합니다. 서버 기본값은 기존 5,000, 웹 값 우선입니다. 환경변수 URS_OPENAI_MAX_OUTPUT_TOKENS도 선택적으로 지원합니다.
- 출력 한도 도달 오류를 직원 화면에 안전하게 표시합니다. 유료 자동 재시도는 하지 않습니다.
- 진단 CLI와 보고서/독립검증/기술분석 및 검증 설정 서명도 같은 설정을 사용합니다. 모델/effort/한도 변경 시 과거 검증으로 승인을 통과시키지 않습니다.
- 현재 단위/HTTP 시험 114개 및 Chromium/HTML 재열기 검증. 유료 호출 검증 및 실제 Codespaces UI 배포는 별도 확인 사항입니다. 실제 사용자 API 연결 성공/출력 한도 도달은 사용자 보고이며 이 개발 시험은 모의 응답입니다.
- 사용 안내: docs/ai-web-settings.md. 새 코드 설치 후 최초 서버 재시작 1회가 필요하며 그 이후 웹 설정 변경에는 재시작이 필요 없습니다.

---

# 사용자 프롬프트 저장 / 로컬 PDF.js 보고서 지원 (2026-11-16)

- 사용자가 제공한 한국어 HTML/PDF.js 프롬프트를 prompts/user-report-ko-html.txt에 보관했습니다. 기본 프롬프트로 자동 주입하지 않습니다.
- 진단 명령의 --save-prompt FILE은 선택한 원본 PDF 직원의 웹 설정에 원문을 새 버전으로 저장합니다. 동일 내용이면 중복 버전을 만들지 않으며 기존 프롬프트 이력/보고서/검증 결과는 보존합니다.
- 최종 HTML의 인라인 JavaScript 및 cdnjs/jsdelivr/unpkg PDF.js/worker 실행을 분리된 sandbox에서 허용합니다. allow-same-origin은 허용하지 않으며 부모 직원 화면 접근, 폼 전송은 차단합니다. 저장된 모델 HTML bytes는 수정하지 않습니다.
- 브라우저 시험에서 실제 PDF.js 3.11.174로 로컬 선택 PDF를 읽어 페이지/빨강·파랑 원본 이미지를 캔버스 픽셀로 확인했습니다. PDF 선택 시 서버 POST가 없고 부모 화면 접근이 차단됨을 확인했습니다. 재현 시험은 Apache-2.0 배포본을 tests/vendor/pdfjs에 보관해 외부 네트워크 없이 실행합니다.
- 실제 API 응답이 HTTP 200이지만 incomplete인 경우를 별도로 기록합니다(api_http_success/api_response_completed/incomplete_reason). HTML 완료나 번역 품질 통과로 오인하지 않습니다.
- 전체 단위/HTTP 현재 시험 104개 및 Chromium/HTML 재열기. 사용자의 실제 키·25페이지 원본으로 성공했는지는 사용자 Codespaces에서 진단 결과를 받은 뒤 판정합니다. 이 개발 시험에는 유료 API 호출이 없습니다.
- 새 JavaScript 실행 정책과 .env 변경을 실행 중인 웹 서버에 적용하려면 서버 재시작이 필요합니다. 프롬프트 DB 저장/진단 자체는 서버를 중지하지 않고 실행할 수 있습니다.

---

# 선택형 reasoning.effort 지원 (2026-11-16)

.env의 URS_OPENAI_REASONING_EFFORT를 보고서·독립검증·분석 API 요청의 reasoning.effort로 전달합니다. 빈 값/미설정은 기존처럼 해당 필드를 생략합니다. 앱에서 허용하는 명칭은 none/minimal/low/medium/high/xhigh이며, 각 모델의 실제 지원 여부는 실제 API 응답으로 확인해야 합니다. 임의의 기본 effort나 모델을 지정하지 않습니다.
보고서 메타데이터와 검증 근거에 effort를 기록하며 설정이 달라지면 기존 검증을 최종 승인에 재사용하지 않습니다. 기존 HTML/운영 자료는 수정하지 않습니다.
진단 CLI의 requested_effort는 실제 설정값을 표시하고 returned_effort는 API 응답 필드가 있을 때만 기록합니다.
추가 시험 3개: 보고서/검토 요청 값 전달(허용값별), 잘못된 값의 네트워크/비용 예약 전 차단, 진단의 설정 표시. 전체 현재 시험 100개. 실제 사용자 API의 모델/effort 지원은 미검증입니다.
.env 저장 후 실행 중인 서버에 적용하려면 서버 재시작이 필요합니다. .env.example은 새 빈 항목만 추가하며 기존 .env를 덮어쓰지 않습니다.

---

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
