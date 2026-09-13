# 실제 backend 결과로 생성하는 100명 데모 데이터와 재생·적용 검증

기존 `generate_data.py`는 최종 CSV 행을 직접 만들어 실제 명령 결과와 금융 이력이 분리될 수 있었다. 이번 변경은 `synthetic_data`가 실제 backend STEP 결과를 읽고 다음 행동을 결정하도록 연결한다. 실제 접근 가능한 피드의 노출이 일부 학생의 목표·배분에 영향을 주며, 완료 명령이 성공해야 완료 이력이 남는다. 최종 CSV는 이 실행 결과를 기존 배치가 읽을 수 있도록 투영한다.

2026-09-13 KST 기준으로 100명 전체 생성, 독립 DATA 오라클, 6 CSV, 전체 원본 입장, 로컬 APPLY·RESTORE 및 비Owner 대표 4명의 로컬 HTTP·DB 검증 증거가 있다. **서로 다른 새 DB에서 18,396개 이벤트씩 완료한 fixed09의 정규화 파일 5개가 모두 일치한다.** 이번 DATA 인계는 실제 파일과 실행 관측을 다시 대조하고 전체 DATA 회귀 87개를 재실행했다. 이 결과는 로컬 기능 재현 검증이며, 대표 4명의 실제 UI 조작과 외부 데모 적용·authoritative read-back은 별도 제품 검증으로 남아 있다.

## 데이터 범위와 행동 정책

대상은 한 학원의 초3~6 각 25명, 총 100명이며 기간은 Asia/Seoul 2026-06-01~09-10이다. 학년별 20명은 6월 1일에, 나머지 5명은 이후에 가입한다. 실제 사용자 로그를 학습한 데이터가 아니라 명시한 가정과 seed에 따른 합성 데이터다. 6월 준비, 7·8월 완전한 주간·월간 마감, 9월 현재 피드를 함께 다룬다.

학생별 seed로 지급 방식·소비·관심사·방문 빈도·공개 범위·영향 수용·목표 크기와 동시 보유 한도를 만든다. 완전 가입 월의 실제 수입은 10,000~30,000원이고 부분월은 실제 지급일만 포함한다. 현금 수입 GRANT와 소비 PURCHASE, 기존 돈의 배분 DEPOSIT/WITHDRAW/TRANSFER를 분리한다. 카드 소비 자체가 위시 배분을 차감하지 않으며 성공한 잔액 관측으로 불일치를 확인한 뒤 사용자 조정 명령을 실행한다.

명령마다 실제 amount/state/version을 읽고, 완료·포기 뒤 대기와 다음 목표, 부분 인출·이체·삭제·공개 변경을 반영한다. 완료 수나 최종 저축 유형·잔액을 강제하지 않는다. 친구무리는 학년 중심으로 형성하되 다른 학년·단방향·소극적 관계도 포함한다. 친구무리 자체는 접근 권한이 아니며 FOLLOWERS는 관찰자가 소유자를 팔로우해야 한다. 노출·클릭·프로필 방문을 구별하고 unmatched click을 실제 기록으로 유지한다.

휴면 동안 지급·소비·마감은 계속되며 복귀는 마지막 실제 앱 활동을 참조한다. 같은 시각에는 주간 마감, 월간 마감, 일반 행동 순서로 실행한다. 리캡은 해당 경계에 고정한 입력과 실제 Python HTTP 응답·저장 결과를 근거로 하며 최종 CSV로 과거 입력을 대체하지 않는다. 정상 NOT_ELIGIBLE에는 존재하지 않는 응답을 만들어 넣지 않는다. 미완료 주간이나 9월 월간 결과도 생성하지 않는다.

## 전체 생성 결과와 CSV 호환성

원본 `full-03`은 backend `DISCOVERY_COMPLETED`이며 100명 모두 실제 JOIN을 완료했다. 총 18,396개 이벤트 중 APPLIED 18,386개, REJECTED 10개다. 거절은 차단 관계의 PROFILE_VISIT/FOLLOW이며 금융 명령 실패는 없었다.

- 위시 222개: 완료 67개, 포기 47개, 진행 중 108개, 삭제 이력 32개. 실제 목표 금액은 5,000~198,000원이다.
- 주간 마감 1,216개, 월간 마감 256개. 정상 NOT_ELIGIBLE 79건에는 실제 HTTP 응답이 없다.
- FEED_QUERY 2,445개, 추천 페이지 2,442개, LATEST 3개. 이어보기 때문에 호출 수와 페이지 수는 다르며 HTTP 시도 2,311개 중 응답 2,310개를 보존했다.
- 실제 신호와 결정을 참조하는 영향 주석 96개, 휴면 복귀 16개, 선행 노출이 있는 클릭 2,005개, unmatched click 92개를 검증했다.
- 독립 DATA 오라클이 이벤트·월 수입·현금 ledger/cache·위시 배분·실제 결과·접근 권한·인과·기간 완결성을 통과했다. 생성 시 backend의 과거 체크포인트·불일치 조정·멱등성·관계형 정규화 및 검증 전후 DB 보존 증거도 남겼다.

| CSV | 행 수 |
|---|---:|
| users | 100 |
| card_accounts | 100 |
| wishes | 222 |
| savings_transactions | 1,693 |
| feed_posts | 138 |
| profile_visits | 1,752 |

기존 주간·월간 배치의 fetch/변환 함수로 CSV를 모두 읽었다. 각 위시의 현재 금액은 부호를 보존한 배분 원장의 합과 일치하며 전체 현재 배분액은 633,196원이다. 종료 시각은 실제 `completed_at`/`abandoned_at`을 투영하고 날짜 파서는 ISO 오프셋·마이크로초를 보존해 KST 비교값으로 변환한다.

## 재현성, 출처와 실패 처리

원본 패키지는 `docs/demo/artifacts/package-04`다. 표준 bundle, 전체 관계형 상태, 5개 정규화 파일, 6 CSV, 생성 소스 스냅샷과 단계별 해시를 함께 보존한다. UUID·커서·HTTP RAW는 변경하지 않는다. 동일한 완료 파일은 바이트 비교 후 hardlink로 공유했으며 manifest의 논리 바이트 수는 그대로다.

| 원본 항목 | 값 |
|---|---:|
| bundle 파일 | 78,095 |
| 패키지 전체 검사 항목 | 78,155 |
| manifest 바이트 | 13,432,329 |
| 최대 개별 artifact 바이트 | 19,967,699 |
| bundle 논리 바이트 | 13,862,132,635 |
| RAW 파일 / 바이트 | 78,085 / 13,828,962,213 |

- dataset: `sha256:4321c0be722100494edb880f16474481a11c2b076a5634bf1815057d075d28bc`
- manifest: `sha256:4aa120ac66807f8052207f9b5da2733030795a2120510ef6cfe2df1bb09496d4`
- DATA HEAD: `3b081b7a51523cdf8d24a6991b7e914e0fd8bc48`
- BACKEND HEAD: `cfd4e400b865a8fbe99b2f27f638b05edf1cfa0e`

구현은 위 HEAD 위의 미커밋 변경을 포함한다. 생성 시작의 sourceOverlayDigest와 원본 소스 스냅샷, 이후 package/admission/application/final 단계의 해시를 구분한다. `stage_inventory`는 실행 소스의 미추적 파일도 해시하고 삭제 파일은 `null`로 기록해 V22 같은 새 migration을 누락하지 않는다. 기존 생성 당시 출처는 수정하지 않는다.

`compare_replays`는 서로 다른 실제 경로와 관측된 DB 이름, 동일 dataset/manifest/요청 이벤트 수, 모든 이벤트 완료, 검증 전후 DB fingerprint 보존과 5개 정규화 파일 일치를 요구한다. 같은 결과 디렉터리·심볼릭 링크·복사된 동일 DB 관측·부분 성공·다른 manifest·DB drift를 두 번의 새 재생 성공으로 인정하지 않는다. 명령 결과·멱등성·실패 기록을 유지하며 모호한 APPLY를 자동 재시도하지 않는다.

피드의 초근접 순위 차이는 Python 보상 합산과 Java 순차 binary64 합산의 차이로 재현하여 명시적 순차 합산 및 회귀 fixture로 수정했다. `full-02` 실패 원본은 보존했다. backend OpenAPI에 대한 피드 projection 원본 digest를 동기화했으며 피드 확장 본문 digest는 동일하다.

## 전체 원본 입장과 backend 연동

현재 reader의 bundle 합계 상한은 16GiB이며 전체 RAW를 유지한 입장 검증이 성공했다. `admission-07/measurement.json`은 13,862,132,635바이트 원본을 exit 0으로 읽었고 82.643초, heap 상한 805,306,368바이트, 실제 최대 RSS 905,478,144바이트를 기록한다. 이는 입장 검사 측정이며 전체 고정 재생의 메모리 측정이나 성공 증거로 확대하지 않는다.

기존 8GiB 상한, 정상 NOT_ELIGIBLE의 응답 참조, `mismatch_notification_outbox` 부모 소속 검사는 과거 실패 원인이다. 현재 backend의 reader·timeline·evidence parser와 V22 `demo_import_notification_ownership` 보수, 관리 import 경로의 테스트 및 로컬 적용·복원 증거를 기준으로 읽는다. V20 대상 clone에 V21·V22를 적용한 실제 검증도 있다. 과거 `backend-blockers.json`이나 package 내부 admission 상태 문자열은 당시 기록으로 보존한다.

현재 backend는 피드 요청 내부의 metric/title 계산을 캐시한다. 완료된 fixed09 runner는 원본 package-04, 6GiB heap, 바이트 검증된 투명 출력 압축과 3GiB 디스크 reserve를 사용했다. 원본 입력을 축소하거나 변경하지 않았다. 두 실행의 종료 코드 0과 실제 정규화 파일을 함께 확인했다.

## Owner 보존과 실제 로컬 APPLY·RESTORE

원본 합성 데이터의 Owner는 PRIVATE/PASSIVE/ISOLATED다. 적용 후보는 기존 대상 Owner 그래프와 합성 99명으로 구성하며 수동 외부잔액 콘솔을 100명으로 확장하지 않는다. 대표 4명은 모두 비Owner다. Owner identity/config/consumption/retry/lookup 보존과 다른 학생의 SIMULATION 출처를 구분한다.

`application-08/verification.json`은 임시 로컬 DB에서 학생 100명·합성 계좌 99개·SIMULATION 관측 3,731개를 적용하고 원래 Owner와 제외 학원을 보존한 PASS, 이후 전체 도메인 테이블·sequence를 복원한 PASS를 기록한다. 따라서 로컬 APPLY·RESTORE는 실제 실행된 상태다.

최신 승인 대상 backup을 로컬로 복제한 `live-target-20260913/clone-02/verification.json`에서도 PASS를 확인했다. V20에서 migration 2개를 적용했고 적용 후 cohort 100명과 유지한 기존 학생 4명, 총 104명이 있다. Owner 위시 107개를 보존했고 원래 도메인 테이블 전체와 sequence 복원을 확인했다. 이 결과는 로컬 clone에 대한 검증이며 `externalDemoWritten`과 `externalConsoleVerified`는 모두 false다.

private backup은 로컬 검증 입력으로만 유지하며 Git에 포함하지 않는다. 본문과 공개 가능한 증거에는 비공개 연결 문자열·계정 비밀값을 기록하지 않는다. `docs/demo/artifacts/`의 대용량 RAW와 live backup은 Git 제외 대상이다.

## 검증 결과와 증거 범위

| 검증 | 확인한 결과 | 증거 |
|---|---|---|
| DATA 회귀 | 이번 액션 87 PASS, 실패 0, skip 0, 5.623초 | `verification-436b06.json`, `verification-436b06/tests-host.log` |
| 원본 package read-back | 이번 액션 78,155개 파일 크기·SHA-256 및 manifest 일치 | `verification-436b06/package-readback.json` |
| 독립 DATA 오라클 | 이번 액션 100명·78,085 RAW 무결성·원장·행동·기간 PASS | `verification-436b06/discovery-oracle.json` |
| 전체 고정 재생 | 새 DB 두 개에서 각 18,396개 완료, 5개 파일 해시 일치 | `verification-436b06/replay-readback.json` |
| 실행 소스 read-back | DATA 47개 파일·backend overlay 26개가 실행 전후 및 현재와 일치 | `verification-436b06/source-readback.json` |
| backend main suite | 698개 중 실패·오류 0, optional skip 1 | backend `docs/demo/verification-runtime-20260913.json` |
| backend simulation suite | 515개, 실패·오류·skip 0 | 같은 backend 검증 파일 |
| 전체 원본 입장 | exit 0, 원본 논리 바이트 유지 | `artifacts/admission-07/measurement.json` |
| 로컬 적용·복원 | Owner·제외 학원·전체 도메인·sequence 보존 PASS | `artifacts/application-08/verification.json` |
| 최신 대상 clone 적용·복원 | V20→22, cohort 100 + 기존 4, Owner 위시 107 보존 PASS | `artifacts/live-target-20260913/clone-02/verification.json` |
| 로컬 runtime readiness | 네 학년 accounts HTTP 200, 일반 DB 역할, import 함수 4개 모두 실행 거부 | `artifacts/live-target-20260913/preview-05/target/ready.json` |
| 대표 4명 로컬 HTTP·DB | 계좌·위시·피드·리캡·타인 계좌 접근 거부·SIMULATION DB read-back PASS | 같은 target의 `api-verification/verification.json` |

DATA 회귀 명령은 `CRABIT_BACKEND_OPENAPI=../crabit-backend/api/openapi.yaml python3 -m unittest discover -s tests -v`다. 이번 액션에서 DATA 테스트와 파일 기반 검증을 새로 실행했다. 초기 sandbox 실행의 2개 오류는 loopback socket 권한 제한이었으며 호스트 실행에서 87개 모두 통과했다. backend suite·APPLY·RESTORE·HTTP 및 약 97분의 고정 재생은 앞선 실행의 증거를 다시 읽었으며 이번에 재실행하지 않았다. preview-05의 backend jar digest는 `sha256:faff8c765244057208a2aa2d13bb5bb5e51a0532360d3e93ba25cd35abd6b8e3`다.

대표 4명 모두 추천 피드 5개와 타인·Owner 계좌 접근 거부를 확인했다. 주간 상태는 모두 SUCCEEDED, 월간은 초4·5 SUCCEEDED 및 초3·6 NOT_ELIGIBLE이다. preview는 일반 runtime DB 역할을 사용하고 관리 import 함수 4개를 모두 거부하며 Owner lookup을 일시 중지했다. preview-05 보고서는 네 대표의 실제 새 HTTP 호출과 SIMULATION DB read-back을 기록한다. 이번 DATA 액션은 해당 결과 파일만 다시 읽었다. 이 증거는 **로컬 HTTP·DB 검증**이며 브라우저 UI 조작이나 외부 적용 성공 증거가 아니다.

## 전체 고정 재생 결과와 남은 제품 검증

`fixed-replays-09`의 첫 DB는 2,876.522초, 둘째 DB는 2,913.497초에 종료 코드 0으로 완료했다. 각각 요청한 18,396개 이벤트 모두 처리했고, 피드 2,311회 시도·2,310회 응답·2,445개 페이지 및 리캡 1,472개를 검증했다. 서로 다른 DB 이름과 검증 전후 fingerprint 보존을 관측에서 확인했다. 이번 액션에서 `compare_replays`를 다시 실행해 실제 backend·relational·responses·feed·recaps 파일의 SHA-256을 비교했고 기록된 comparison과 일치했다.

실행 전후의 DATA 47개 실행 소스와 backend overlay 26개는 서로 같고 이번 read-back 시점의 파일과도 같다. DATA HEAD는 `3b081b7a51523cdf8d24a6991b7e914e0fd8bc48`, backend HEAD는 `cfd4e400b865a8fbe99b2f27f638b05edf1cfa0e`이며 미커밋 overlay를 포함한 검증이다. SHA만으로 변경이 이미 커밋됐다고 표시하지 않는다.

고정 재생은 명시적인 30,000ms 피드 예산을 사용한다. 원본 e17164의 응답 부재는 새 실제 Python 응답을 35초 보류해 재현했고, 두 실행에서 각각 한 번의 주입과 proxyFailures 0개가 기록됐다. 실제 서비스와 discovery의 500ms 제한은 유지한다. `servingLatencyPolicyValidated=false`이며 이 기능 재현 결과는 서비스 성능 증거가 아니다.

05~08 실패 기록은 보존했다. 05는 DB 연결 오류, 06~07은 피드 deadline 불일치였다. 08은 11,095개 처리 후 e11096에서 중단됐으며 같은 시각 공유 카드의 UUID 정렬 차이가 실제 Python 후보 순서를 바꿨다. backend의 후속 수정은 기록된 공유 카드 identity 169개를 사용해 두 새 DB의 동률 순서를 재현한다. 수정 이후의 09 두 전체 재생이 통과했다. DATA에서 기대값이나 비교 조건을 완화하지 않았다.

backend 관측의 정확한 상태는 두 실행 모두 `REPLAYED_PARTIAL_VALIDATION`이고 `fullDatasetValidationPerformed=false`, `readyForApplication=false`다. 전체 이벤트 완료와 엄격한 파일 일치, DATA 독립 오라클 PASS는 각각의 검증 범위로만 보고한다. 이 인계의 ready는 DATA 구현을 다음 controller 검증에 넘길 수 있다는 뜻이며 integration/review/final gate나 외부 적용 승인이 아니다.

backend read-back 보고서 `docs/demo/verification-full-replays-20260913.json`의 SHA-256 `9feeccdee749fcd529b78c62cf59379e842de87b22f2a5e34d182d1270641c24`도 직접 확인했고 comparison·각 실행 관측·소스 digest가 실제 파일과 같다. 부모의 최종 backend 전체 suite는 session 25369에서 진행 중이라는 인계를 받았으며 이번 DATA 검증에서 통과로 간주하지 않았다.

대표 4명의 실제 브라우저 UI 흐름과 수집 검증, 외부 데모 적용 후 추천 피드·주간/월간 리캡 및 Owner 콘솔 authoritative read-back은 부모 workflow의 별도 작업으로 남아 있다.

## 변경 범위와 전달

이 DATA 구현의 계획 globs 밖 인접 변경은 `.gitignore`, `feed/ranking.py`, `api/feed-ranking-v1.yaml`, `tests/test_feed_contract_projection.py`, `monthly_batch.py`, `weekly_batch.py`다. 각각 대용량/private artifact 제외, 실제 피드 순위 일치와 계약 회귀, 기존 CSV 소비자의 종료 시각·시간대 호환을 위해 필요했다. 이번 액션은 계획 범위 안의 `docs/demo/pull-request.md`, `docs/demo/verification-436b06.json` 및 `docs/demo/verification-436b06/` 검증 산출물을 작성했다. 실행 소스 변경은 없고 위 6개 인접 변경은 기존 DATA 구현에서 인계된 항목이다.

기존 `action-evidence.json`, `dataset-summary.json`, `backend-blockers.json`, `test-evidence.json`, `specialist-envelope.json`, `replay-readiness-17ddf5.md` 및 실행 artifact는 당시 증거로 보존한다. 이번 액션의 검증은 별도 파일로 기록한다. commit/push/원격 PR 생성, backend/frontend 소스 변경, Feature Run/action/receipt 변경 또는 외부 provider 쓰기는 수행하지 않았다. 이 문서는 controller가 제출할 상세 한국어 PR의 로컬 초안이다.
