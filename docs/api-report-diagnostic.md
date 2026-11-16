# 현재 API / HTML / 이미지 연결 확인

웹 서버를 끄지 않고 같은 Codespaces의 새 터미널에서 실행합니다.

```bash
git pull && python scripts/check_api_report.py --call
```

현재 실행 중인 서버의 기존 API 연결을 대신 확인했다고 주장하지 않습니다. 이 명령은 동일한 Codespaces의 환경변수와 .env 파일을 서버와 같은 규칙으로 읽고, 현재 코드의 생산용 OpenAI 어댑터로 별도 진단 요청을 합니다. 서버 시작 이후 .env를 변경했다면 실행 중인 프로세스 설정과 다를 수 있습니다.

기본 문서는 마지막에 업로드한 PDF입니다. 그 문서를 보유한 직원의 최신 웹 저장 프롬프트를 사용합니다. 특정 문서는 --document DOCUMENT_ID로 선택합니다. 프롬프트가 없거나 비어 있으면 임의 프롬프트를 만들지 않고 API 호출을 차단합니다.

출력:
- api_key_present: 키 존재 여부만, 키 값은 출력하지 않음.
- prompt_saved/version/bytes/sha256: 저장 여부 및 버전; 프롬프트 본문은 출력하지 않음.
- requested_model: 현재 환경 설정의 요청 모델. returned_model: 실제 API가 돌려준 모델.
- requested_effort: URS_OPENAI_REASONING_EFFORT 설정값. 빈 값이면 null이며 요청에서 생략합니다. returned_effort는 실제 응답 필드가 있을 때만 기록하며 없으면 미확인.
- api_call_verified: 실제 HTTP 200 + completed 응답에 한해 true.
- live_request: 실제 HTTP 상태, 요청/응답 식별자, 원본 PDF/프롬프트 동일 여부, usage. 인증 헤더/키/본문은 출력하지 않음.
- html_image_only_verified: 모델 원본과 최종본의 주소 사이 모든 문자열이 동일한지 별도 비교.
- images_inserted/unresolved_images: 치환한 이미지 수 및 못 찾은 자리.
- existing_reports_and_stages_unchanged: 기존 결과물·단계 결과를 호출 전후 대조.

진단 HTML은 .runtime/diagnostics의 새 디렉터리에만 보관합니다. 원본 PDF/기존 보고서 재생성·덮어쓰기는 하지 않으며, 실제 호출에 따른 ai_usage 원장 행만 추가합니다. 비용 한도와 모델 설정을 바꾸지 않고, 네트워크/모델 응답을 모의 응답으로 대체하지 않습니다.

`--call` 없이 실행하면 읽기 전용 조회이며 유료 호출이 없습니다. 시험 코드의 응답 모의 처리는 진단 코드 시험에만 쓰이고, CLI 실행에는 적용하지 않습니다.

## effort 설정

.env에 URS_OPENAI_REASONING_EFFORT=high 처럼 원하는 값을 적습니다(예시). 빈 값은 기존 API 기본값을 유지합니다. 모델이 지원하는 명칭은 실제 API 응답으로 검증해야 합니다. 키/모델/effort 등 .env 변경은 서버 재시작 후 웹 서버에 적용됩니다. 진단 CLI는 실행할 때마다 .env를 새로 읽습니다.

## 이번에 지정한 사용자 프롬프트 저장과 호출

```bash
git pull && python scripts/check_api_report.py --save-prompt prompts/user-report-ko-html.txt --call
```

이 명령에 한해, 최근 원본 PDF를 보유한 직원의 웹 프롬프트 설정에 제공된 원문을 저장하고 API 진단을 실행합니다. 기존 프롬프트 버전은 지우지 않으며 같은 원문이면 저장 버전을 반복 생성하지 않습니다. 다른 직원/문서는 --document ID로 명시할 수 있습니다.
진단은 기존 운영 보고서를 생성/교체하지 않고 새 .runtime/diagnostics에만 HTML을 저장합니다. 최종 HTML에서 이미지 주소 바깥 문자열의 일치 여부를 별도로 비교합니다.
api_http_success는 실제 HTTP 200, api_response_completed는 공급자의 completed 응답입니다. incomplete_reason=max_output_tokens 등이면 HTML 완성을 확인한 것으로 보고하지 않습니다.
새 프롬프트의 브라우저 PDF 선택은 최종 HTML 내부에서 처리하는 기능입니다. 앱에 원본을 처음 등록·보관하고 OpenAI에 입력 파일을 전달하는 흐름은 별개이며 유지합니다.

image_binding_exercised는 실제 이미지 주소 치환이 1회 이상 수행된 경우에만 true입니다. 모델이 PDF.js/canvas 방식만 출력해 치환 자리가 없으면 0회/false로 기록하며, 이미지 삽입이 실제 검증됐다고 보고하지 않습니다.
