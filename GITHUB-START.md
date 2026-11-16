# GitHub에서 실행하기

1. 저장소의 **Code → Codespaces → Create codespace on main**을 누릅니다.
2. 초기 Python 3.12 환경과 의존성 설치가 끝날 때까지 기다립니다.
3. Codespaces 터미널에서 `python start.py`를 실행합니다.
4. 첫 실행 때 직원 ID와 12자 이상의 비밀번호를 만듭니다.
5. **Ports** 탭의 **8795** 포트에서 지구본 아이콘(Open in Browser)을 누릅니다.

브라우저가 자동으로 열리지 않아도 Ports 탭에서 열 수 있습니다.
포트 공개 범위는 기본 비공개 상태로 유지하세요. 실제 웹 주소는 Codespaces가 만듭니다.
Codespace가 정지되면 웹도 정지됩니다. Codespaces는 계정의 무료 사용량 또는 요금 정책을 따릅니다.

원본의 API 인증 및 실제 문서 품질 등 미해결 항목은 그대로입니다.
.env는 GitHub에 업로드하지 않았습니다. API를 사용하려면 .env.example을 .env로 복사하고 본인 설정을 입력하세요.
업무 데이터는 .runtime에 보관되며 Git에 포함되지 않습니다. Codespace를 삭제하기 전 필요한 데이터를 별도 백업하세요.

이 설정은 작성 및 JSON 검증을 마쳤으나, 실제 Codespaces 생성은 이 환경에서 검증하지 않았습니다.
