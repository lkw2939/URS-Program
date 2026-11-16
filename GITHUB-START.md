# GitHub Codespaces에서 웹 켜기/끄기

## 현재 열려 있는 Codespace에 적용

기존 서버가 터미널에서 실행 중이면 그 터미널에서 Ctrl+C로 한 번 종료합니다. 다음을 실행합니다.

```bash
git pull
python start.py
```

첫 실행일 때만 직원 계정을 만듭니다. 이후 웹은 백그라운드에서 실행되므로 터미널을 닫아도 유지됩니다. Ports 탭의 8795 포트에서 브라우저 열기를 누릅니다. 기본 비공개 포트 설정을 유지하세요.

기존 Codespace에 자동 시작 설정까지 적용하려면 코드를 받은 뒤 Ctrl+Shift+P → **Codespaces: Rebuild Container** (또는 **Dev Containers: Rebuild Container**)를 한 번 실행하세요. 사용자 파일/계정은 workspace의 .runtime에 유지됩니다. 이후 Codespace가 시작될 때 자동 실행되며, 브라우저를 닫는 것만으로 서버를 종료하지 않습니다.

## 필요할 때만 종료하고 다시 켜기

```bash
python service.py stop
python service.py start
python service.py status
```

각 줄은 별도 명령입니다. stop으로 끄면 수동 종료 상태를 기억하여 다음 Codespace 시작 때도 자동 실행하지 않습니다. start로 다시 켜면 이 상태를 해제합니다.
서버 프로세스가 오류로 종료되면 감독 프로세스가 다시 실행합니다. 빠른 실패가 반복되면 재시도 간격을 최대 30초까지 늘립니다. 로그는 .runtime/server.log에 저장되고 Git에는 올라가지 않습니다.
첫 실행에 계정이 없으면 자동으로 임의 계정을 만들지 않으며 python start.py 안내만 표시합니다.

## 계속 켜짐의 범위

이 기능은 **Linux/Codespaces 컴퓨터가 실행되는 동안** 터미널과 서버 수명을 분리합니다. Codespaces 자체의 유휴 시간 초과·정지·삭제·사용량 한도·네트워크 중단은 막지 못합니다. Codespace가 중단된 동안 웹은 접속할 수 없습니다. GitHub의 Codespace 유휴 중지 설정과 계정 요금/사용량 정책이 적용됩니다.
24시간 접속이 필요하면 상시 실행되는 별도 서버에 배포해야 합니다. 이번 변경은 외부 유료 서버 개설, Codespaces 요금/절전 설정 변경, 절전 회피 동작을 하지 않습니다.
Windows에서는 기존 python start.py 전경 실행을 유지합니다. service.py는 Linux/POSIX용입니다.

## 데이터와 API

.env와 .runtime DB는 Git에 올리지 않습니다. Codespace를 삭제하기 전 필요한 업무 데이터는 백업하세요.
서비스 재시작은 기존 계정·세션·원본·보고서를 보존하고 보고서를 자동 생성하지 않습니다. API 호출/인증/고객 문서 품질의 미해결 상태는 그대로입니다.

검증: 임시 DB에서 실제 자식 프로세스 분리·중복 시작 방지·비정상 종료 후 복구·수동 종료 유지·재시작·데이터/세션 보존을 시험했습니다. 실제 사용자 Codespace의 중지/재개는 이 연결 권한으로 직접 시험하지 못했습니다.
