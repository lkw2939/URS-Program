# 1단계 검토 자료

## 구현 결과

- `urs/workflow.py`: SQLite 트랜잭션, 고정된 체크리스트 정의, 문서 리비전, 검증 결과, 근거 SHA-256, 검사기 이름/버전/시각, 감사 이력, 승인 저장.
- `urs/server.py`: 내부 루프백 HTTP API. bearer 인증 필수. 클라이언트가 PASS를 전달할 수 없고 서버에 등록된 검사기만 실행한다. 직원용 로그인 화면이나 배포 서버가 아니다.
- `urs/gates.py`: 기본 통과 정책.
- `docs/requirements-map.json`: 33개 요구사항 및 추가 5개 항목의 개발 단계 매핑.

## 항목별 검증 근거

| 항목 | 시험 근거 |
|---|---|
| S1-01 | `test_requirements.py`: 38개 정확한 ID 집합 및 단계 범위 확인 |
| S1-02 | `test_definitions_are_persistent_and_frozen`: 재연결 복원, 정의 교체·빈 목록·중복 거부 |
| S1-03 | `test_gates.py`, `test_all_nonpassing_statuses_block_next_stage`: 전 상태, 누락, 중복, 근거, 리비전 검사 |
| S1-04 | `test_http_sequence_and_forgery`: 다음 단계 직접 요청 409, 검증 후 허용 |
| S1-05 | `test_full_flow_persistence_and_invalidation`, `test_rerun_clears_downstream_and_approval`: 수정 및 상위 재검증 시 승인/후속 결과 무효화 |
| S1-06 | `test_full_flow_persistence_and_invalidation`: DB 재연결 후 결과/승인/이력 복원 및 근거 해시 일치 |
| S1-07 | `test_cannot_forge_automatic_pass`, `test_concurrent_edit_during_validation_rejects_result`, HTTP 시험: 수동 PASS 및 변조 요청 거부, 인증 없는 요청 401, 오래된 결과 거부 |
| S1-08 | HTTP 시험: 차단→검증→다음 단계→사람 검토→승인→수정→재차단 |
| S1-09 | 검증 결과 및 범위를 제시한 뒤 사용자의 “진행” 지시를 개발 착수 허용으로 기록. 별도의 사람 기술 검증을 했다는 주장은 아님 |

## 시험 결과

`python -m unittest discover -s tests -v`: 16개 통과, 실패 0, 건너뜀 0. 로그: `docs/evidence/stage1-tests.txt`.

통합시험의 검사기는 합성 입력의 비어 있음과 해시만 확인한다. PDF, 실제 번역, 의미 정확도, 고객 문서 검증을 대신하지 않는다. 시험용 사람이 등장하는 호출은 실제 직원 승인으로 기록하지 않는다.

## API 사용 범위

`make_server(workflow, validators, token)`으로 서버를 구성한다. 서버 코드가 체크리스트와 검사기를 등록하며 API로 검사기를 추가하거나 정의를 바꿀 수 없다. token은 최소 32자이며 안전한 난수로 생성해 내부 실행자에게만 제공한다. 현재 실행 중인 상시 서버는 없다. 시험 서버는 시험 후 종료한다.

- `GET /jobs/{id}`: 현재 상태와 검증 이력
- `POST /jobs/{id}/create`: content
- `POST /jobs/{id}/edit`: revision, content
- `POST /jobs/{id}/run`: stage만 허용
- `POST /jobs/{id}/approve`: revision; 전체 단계 통과 필수

사람 검토 기록은 현재 신뢰된 내부 Python 호출로만 허용한다. 직원용 검토 API는 2단계 계정·권한 도입 후 제공한다. DB를 수정할 수 있는 서버 관리자에 대한 변조 방지나 외부 감사 저장소는 이 단계의 보장 범위가 아니다.

## 다음 단계 진입 조건

사용자가 “진행”을 지시하여 2단계 개발 착수를 허용했다. 매 개발 단계마다 추가 확인을 요구하는 자체 절차는 반복하지 않는다. 실제 고객 문서의 최종 직원 승인은 이 결정과 별개이며 미검증 상태를 PASS로 바꾸지 않는다.
