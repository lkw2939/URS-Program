# 다운로드 후 실행 안내

이 ZIP은 URS AI REPORT SYSTEM 소스 배포본이다. 설치형 EXE가 아니며 Python 3.12가 필요하다. 기존 guion-vivo 프로젝트는 포함하지 않는다. 실제 키/고객 DB/백업/가상환경은 제외했다. 원래 코드와 검증 자료·한국어 글꼴·라이선스·체크리스트는 포함한다.

## Windows PowerShell

ZIP을 풀고 urs-ai-report 폴더에서:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m urs add-user 직원ID
.\.venv\Scripts\python.exe -m urs serve --port 8795
```

## macOS / Linux

Python3.12가 설치된 상태에서 urs-ai-report 폴더에서:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip check
.venv/bin/python -m urs add-user 직원ID
.venv/bin/python -m urs serve --port 8795
```

의존성 설치는 인터넷 연결이 필요하다. 직원ID는 사용할 로그인 이름으로 바꾼다. 비밀번호는 터미널에서 두 번 숨김 입력한다. 기본 계정/비밀번호는 없다. 서버 실행 후 같은 PC의 브라우저 주소창에 http://127.0.0.1:8795 를 입력한다. 종료는 Ctrl+C다. 재실행할 때는 serve 명령만 실행하면 된다.

## 설정과 데이터

로컬 API 설정을 하려면 .env.example을 .env로 복사하고 편집기에서 값을 입력한다. 기존 Codex의 프록시 대체값을 복사하지 말고 로컬 PC에서는 실제 API 비밀 키를 안전하게 저장한다. 키를 채팅·소스 공유·버전 관리에 넣지 않는다. 모델과 단가는 실제 사용하는 모델에 맞춰야 한다. 주입된 환경변수가 있으면 .env보다 우선한다. 설정을 바꾼 뒤 서버를 재시작한다.

API가 없어도 로그인·프로젝트·PDF 원본 보관·원문 검토 기능은 사용할 수 있다. 실제 번역·AI 검증·분석·대화에는 유효한 API 연결이 필요하다. 이번 클라우드 환경의 API 인증401 문제는 해결되지 않았으며, 이 ZIP이 인증 성공을 보장하지 않는다.

업무 데이터는 기본 .runtime/workspace.sqlite에 저장된다. 이 폴더는 개인/회사 자료이며 소스 재공유 때 제외한다. 기존 운영 자료를 지우거나 덮어쓰지 않는다. 백업/복구와 직원 비밀번호 초기화는 docs/operations.md를 따른다.

## 검증 범위와 한계

기존112개 자동시험과 Chromium/LibreOffice 결과는 docs/evidence/validation-summary.json에 있다. API 응답은 고정 합성 자료로 시험한 범위다. 실제 고객 번역 품질·99% 정확도·전문가 평가·회사 직원 최종 승인은 미완료다. 최종 승인에는 현재 코드/모델의 실제 전문가 평가 자격과 출력물4개 검토가 필요하다. 임의로 게이트를 해제하거나 합성 평가를 운영DB에 등록하지 않는다.

이 배포본은 현재 Linux 환경에서 압축 해제/패키지 경로/CLI 기동을 확인했다. 사용자의 Windows/macOS에서 새로 설치하는 과정은 직접 검증하지 않았다. Chromium/LibreOffice 회귀시험은 해당 시스템 프로그램을 별도로 설치해야 하며 일반 앱 기동에는 필요하지 않다. 앱은 루프백 전용으로, 공개 배포/사내 여러 PC 접속은 별도 운영 설정이 필요하다.

전체 상태: docs/PROGRESS.md / 원본 요구사항: docs/requirements-original.md / 인계: docs/HANDOFF.md.
