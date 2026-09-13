# DATA 정책과 검증 범위

## 입력과 실제 행동

이번 자료는 관측된 아동 행동이 아닌 가정 기반 합성 학생 100명의 시뮬레이션이다. 기간은 Asia/Seoul 2026-06-01 00:00부터 2026-09-11 00:00 직전까지다. 학년별 25명 중 20명은 6월 1일, 나머지 5명은 7월 1일·7월 15일·8월 1일·8월 17일·9월 3일에 가입한다. 학년별 비Owner `student-<grade>-01`이 UI 대표다.

학생별 고정 seed에서 월 수입 기준, 지급 방식, 관심사, 위시 배분·소비 성향, 방문 빈도, 공개 범위, 사회적 호기심, 영향 수용 여부, 목표 동시 보유량을 결정한다. 월 수입은 매월 변동하되 완전 가입 월에 10,000~30,000원이다. 주간·월간·불규칙 지급의 전체 달력 일정을 먼저 정하고 가입 전이나 종료 후 지급을 제외한다. 부분월의 최저 수입을 맞추기 위해 미래 지급을 당겨오지 않는다.

현금 수입은 GRANT, 실제 소비는 PURCHASE다. DEPOSIT은 이미 가진 현금을 위시에 배분하고 WITHDRAW·TRANSFER·완료/포기 환급은 배분만 바꾼다. 각 명령의 실제 잔액·위시 amount/state/version을 읽고 다음 명령을 구성한다. 최종 잔액을 직접 지정하거나 보정 거래로 맞추지 않는다. BALANCE_LOOKUP 후 실제 불일치를 발견한 경우에만 허용된 부분 인출을 시도한다.

대부분 목표는 5,000~20,000원, 일부는 21,000~70,000원, 소수는 71,000~200,000원이다. 학생별 목표 동시 보유 한도는 대개 1~2개, 소수 3개이고 완료/포기 후 대기 동안 0개가 될 수 있다. 목표 날짜 유무·관심사·완료 확인 확률·완료 후 대기기간도 다르다. 특정 저축 유형으로 분류되도록 최종 결과를 배정하지 않는다.

공개 범위는 ACADEMY/FOLLOWERS/PRIVATE를 50/30/20 가중치로 선택한다. 이는 정확한 최종 인원 비율이 아니다. 같은 학년의 친구 집단과 학년 간 관계를 모두 허용하며 실제 FOLLOW/UNFOLLOW/BLOCK/UNBLOCK을 실행한다. 이체, 일부 인출, 완료, 포기, 삭제, 공개 범위 변경은 실제 서비스가 수락한 결과로 기록한다.

## 피드, 방문과 인과 관계

일반 학생의 약 25%는 주 3~5일, 나머지는 주 0~2일 방문하도록 고정 seed 일정을 만든다. 가입일과 휴면 복귀일은 추가 방문일이 될 수 있다. 실제 FEED_QUERY 결과에서 1~2개 카드의 노출을 기록하고 성향에 따라 클릭과 프로필 방문을 실행한다. 일부 커서 다음 페이지, DIRECT 프로필 방문, 노출 없이 도착한 unmatched click을 별도로 기록한다. 클릭만 보고 노출을 만들어내지 않는다.

영향을 수용하는 학생은 월 1회까지 실제 노출/클릭/프로필 방문 카드의 위시 목적·목표 금액을 참고한다. 여유가 있으면 새 CREATE, 목표 한도가 찼으면 기존 목표에 의미 있는 DEPOSIT을 시도한다. 그 뒤 계약이 요구하는 INFLUENCED_DECISION을 기록하며 신호 eventId와 실제 결정 eventId를 모두 원인으로 연결한다. 주석은 금융 변동을 수행하지 않는다. EDIT 같은 비승인 명령을 추가하지 않는다.

피드 추천은 실제 Python HTTP 요청/응답으로 실행한다. backend가 반환한 LATEST와 RECOMMENDATION을 구별하고 원본을 보존한다. Python 3.12 이후 `sum`의 보상 합산으로 인한 초근접 점수의 실행 환경 차이를 막기 위해 `feed/ranking.py`는 binary64 순차 합산을 명시한다. 실제 full-02 event 3099의 입력과 독립 Java 오라클 순서를 회귀 fixture로 보존했다.

## 휴면과 마감

초기 학생 일부는 7월에 1~3주 앱 활동을 쉬도록 선택한다. 7월 7일을 마지막 실제 앱 활동으로 남기고 예정된 복귀일에 RETURN_FROM_DORMANCY를 기록한다. 계약상 마지막 실제 활동을 참조하며 존재하지 않는 DORMANCY event를 만들지 않는다. 지급·소비·마감은 앱 활동으로 세지 않는다.

모든 완전 포함 주간과 월간을 정시에 마감한다. 같은 경계에서는 주간, 월간, 그날 일반 활동 순으로 처리한다. 초기 80명은 각 14회 주간과 3회 월간 대상이고 늦은 가입자는 완전히 포함된 기간만 대상이다. 마지막 완전 주간은 8월 31일~9월 7일이다. 종료 시점의 미완료 주간이나 9월 월간을 만들지 않는다. backend가 생성한 고정 기간 입력·실제 Python recap 응답·저장 응답을 원본으로 보존한다.

## Owner와 적용 범위

Owner는 PRIVATE/PASSIVE/ISOLATED이며 다른 99명의 피드·방문·관계가 Owner의 합성 금융 객체를 참조하지 않도록 한다. 로컬 원본에는 100명의 시뮬레이션을 보존한다. 관리 CLI 적용 후보는 대상 Owner 원래 그래프와 합성 99명이다. 학년 대표 4명은 모두 비Owner다.

`verify-application`은 backend 실제 migration으로 새 로컬 DB를 만들고 기존 Owner의 23,456원 PROVIDER 관측·원장·위시와 제외 학원 표식을 준비한다. PREPARE/SQL dry-run/rollback, 단일 APPLY, 별도 INSPECT, RESTORE_PREPARE/단일 APPLY/INSPECT를 수행한다. 실패하거나 결과가 불명확한 APPLY를 자동 재시도하지 않는다. 이는 외부 데모나 실제 Owner 콘솔 read-back을 대신하지 않는다.

## 산출물과 판정

`bundle/`은 고정 계약의 config/students/personas/events/id-map/state/validation/normalized/schema/raw index와 모든 참조 RAW를 담는다. 원본 UUID·커서를 유지한다. 비교용 5개 backend 정규화 파일, 전체 관계형 export, 6개 CSV는 package의 별도 경로에 보존하고 checksum으로 연결한다. CSV는 실제 저장 행의 투영이며 `wishes.saved_amount`는 종료 시점 실제 배분 금액이다. 이전 금융 이력은 원장에 남는다.

DATA 독립 검증기는 가입·기간 경계·월 수입·현금 ledger/cache·명령 결과와 위시 상태·공개/팔로우/차단 접근권한·실제 피드 순서·노출 참조·휴면·영향의 인과 관계를 검사한다. 고정 bundle은 새 DB 두 곳에서 전체 재생한 뒤 `normalized-backend`, `normalized-relational`, `normalized-responses`, `normalized-feed`, `normalized-recaps`를 바이트 단위로 비교한다. 일부 이벤트 검사나 FINISH 전 EOF는 전체 PASS가 아니다.

허용 상한은 files 262,144개, manifest 128 MiB, 개별 artifact 128 MiB, artifact 합계 8 GiB다. 실제 bytes와 파일 수, Java 프로세스 전체의 `/usr/bin/time -l` 최대 RSS를 별도로 측정한다. 상한 자체를 실제 사용량으로 보고하지 않는다. 실행 도중 산출물은 불완전하다. 최종 검증 상태·측정값·실패 기록은 `pull-request.md`와 `action-evidence.json`을 따른다.

## 이번 실제 실행 판정

`full-03`은 100명·18,396개 이벤트·1,472개 마감을 FINISH하고 전체 DATA 오라클을 통과했다. `package-04`의 6 CSV도 실제 배치 fetch/변환과 각 위시의 원장 합계 대조를 통과했다. 전체 bundle 합계는 13,862,132,635바이트이며 8 GiB 입장 한도를 초과한다. 정상 NOT_ELIGIBLE 79건의 필수 응답 참조 모순도 남았다. `--retain-unadmitted`는 이 실제 증거를 보존하면서 용량/참조 실패를 기록하는 옵션이며 한도를 변경하거나 입장 성공을 뜻하지 않는다.

호스트 자동 승인 검토에서 고정 재생이 거절돼 두 새 DB 재생은 실행하지 않았다. 기존 읽기 전용 입장 검사는 실제 `total bundle byte limit` 거절을 반환했다. 별도 로컬 관리 PREPARE는 `mismatch_notification_outbox`의 부모 소속 검사 부재로 거절됐고, 그 뒤 실제 INSPECT로 fingerprint와 journal이 그대로임을 확인했다. APPLY·RESTORE·외부 적용은 미실행이다. 전체 실행을 통과한 것처럼 이 한계를 생략하지 않는다.
