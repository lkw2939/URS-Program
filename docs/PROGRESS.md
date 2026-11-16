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
