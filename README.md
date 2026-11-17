> Linux/Codespaces 실행을 단일 서비스 관리 경로로 통일했습니다. `git pull && python start.py`로 적용합니다. 터미널 종료 후 유지, 서버 종료/연속 HTTP 실패 복구, 수동 종료 상태 보존을 지원합니다. [실행 안내](GITHUB-START.md). 실제 사용자 환경의 외부 접속은 별도 확인이 필요합니다.

# URS AI REPORT SYSTEM — 직접 HTML 보고서

최신 구현: 업로드한 원본 PDF와 웹 설정의 보고서 프롬프트 원문을 OpenAI의 기존 설정 모델에 전달하고, 받은 HTML의 이미지 주소만 원본 사진·도면으로 연결합니다. 텍스트 추출·블록 번역·고정 Word/PDF 제작 기능은 제거했습니다.

[현재 동작/검증 범위](docs/direct-html-report.md) · [최신 진행 상태](docs/PROGRESS.md) · [Codespaces 실행 안내](GITHUB-START.md)

Python 3.12에서 `python start.py`로 실행합니다. 기존 DB와 원본·역사 자료는 유지합니다. 실제 API 인증/고객 품질/99% 정확도는 미검증입니다.

아래는 배포 초기 버전의 설명입니다. 추출/블록 번역/Word·PDF 제작에 관한 설명은 현재 실행 흐름에 적용되지 않습니다.

---

# URS AI REPORT SYSTEM

우도산기 직원이 해외 고객 URS를 보관·번역·검증·분석·수정·출력·승인하는 통합 웹 프로그램이다. 기존 guion-vivo와 별도 프로젝트다.

**현재 판정:** 비API 지원 기능은 로컬/합성 검증 범위에서 구현됐으며, 실제 고객 업무 완성은 미입증이다. 실제 API 인증은 실패했던 상태로 사용자 지시에 따라 보류한다. 사용자 키가 틀렸다고 확정하지 않는다.

[최신 전체 체크리스트](docs/PROGRESS.md) · [원본33개+추가5개 인수 조건](docs/completion-checklist.md) · [정의서19개 장 대조](docs/full-definition-review.md) · [검증 보고서](docs/validation-report.md)

## 실행

Python3.12, 프로젝트 루트에서:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip check
.venv/bin/python -m urs --data .runtime/workspace.sqlite add-user 직원ID
.venv/bin/python -m urs --data .runtime/workspace.sqlite serve --port 8795
```

비밀번호는 숨김 입력한다. 기본 계정은 없다. 서버는 루프백 전용이며 공개 웹사이트로 배포하지 않았다. 프로세스 재시작 시 같은 DB 경로를 사용한다. .env는 자동 로드하되 기존 주입 환경변수를 덮어쓰지 않는다. 키·고객자료·DB·백업을 소스 묶음에 넣지 않는다.

## 직원 업무 흐름

로그인→프로젝트/PDF 등록→원본 보관→전체 페이지/표/그림 대조→한국어 번역→독립 문장/문서 검증→최대2회 오류 수정/재검증→설비 분석/사양 충돌/고객 질의→Word/PDF4개 검토→직원 승인.

미통과·미실행·불확실·필수 조건 부족 상태에서는 다음 정식 단계와 최종 승인을 차단한다. 수정하면 새 리비전으로 검증·출력·승인을 무효화한다. UI 진행 수는 정확도 점수가 아니다. 승인본은 검토 본문을 보존하고 승인 기록을 추가한다.

## 운영자 명령

```bash
.venv/bin/python -m urs --data .runtime/workspace.sqlite reset-password 직원ID
.venv/bin/python -m urs --data .runtime/workspace.sqlite backup .runtime/backups/새백업.sqlite
.venv/bin/python -m urs --data .runtime/새복구.sqlite restore .runtime/backups/새백업.sqlite
.venv/bin/python -m urs check-terminology 검토완료용어집.json
.venv/bin/python -m urs import-terminology 검토완료용어집.json
.venv/bin/python -m urs record-evaluation 전문가평가.json
```

[운영 안내](docs/operations.md) · [백업/복구](docs/backup-restore.md) · [용어 원문 검토/등록](docs/terminology-policy.md) · [실제 전문가 평가 형식](docs/evaluation-format.md). 합성 평가·가짜 출처를 실제 업무 DB/용어집에 등록하면 안 된다.

## 재현 검증

```bash
python scripts/validate.py
```

기초→직원/원본/복구→PDF→의미 보조 검사/용어/평가→문서 처리의 순서로 실행한다. 실패·시험0개·건너뜀·예상 실패는 후속 실행을 차단한다. 이후 Chromium 전체 흐름과 LibreOffice 검토본/승인본4개를 검사한다. 브라우저/Office는 호스트 Playwright·Chromium·soffice가 필요하다. AI는 격리 고정응답이며 실제 OpenAI를 호출하지 않는다. 최신 시험 수/종료 코드/해시는 docs/evidence/validation-summary.json을 따른다.

## 지원 범위와 완료하지 않은 조건

PDF20MB/100페이지, 렌더링/미리보기 한도를 적용한다. 원본은 불변 보관하고 표/셀/좌표·원본 페이지 이미지를 연결한다. 원본의 픽셀 단위 동일 서식을 보장하지 않는다. 실제 스캔/도면 문자·복잡한 표·레이아웃과 번역/분석 품질은 실제 문서 대조가 필요하다.

실제 고객 URS, 공식 한미 기술 자료 원문/판본 승인, 전문가 문장 의미99% 이상·중대 기술/안전 오역0, 실제 직원 접속 환경/업무 인수는 별도 미완료다. 실제 API 인증/모델/비용/공급자 자동충전 점검은 보류한다. 관련 설정은 URS_OPENAI_API_KEY, URS_OPENAI_MODEL, URS_AI_BUDGET_USD, URS_AI_INPUT_USD_PER_MILLION, URS_AI_OUTPUT_USD_PER_MILLION이다. 단가는 기본 비용 예약용이며 공급자 모든 가산요금의 정확한 청구 상한은 아니다.

다음 작업은 AGENTS.md와 docs/HANDOFF.md 및 docs/checklist.md를 먼저 읽는다.
