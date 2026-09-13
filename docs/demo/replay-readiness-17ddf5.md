# DATA 재생 검증 재개: act-17ddf5

이번 액션은 `demo-student-behavior-simulation` revision 15의 DATA 구현 작업이다. 기준 HEAD는 `3b081b7a51523cdf8d24a6991b7e914e0fd8bc48`이며 수정은 미커밋 상태다. Feature Run/action/receipt 및 다른 저장소 소스는 수정하지 않았다.

## 수정한 검증 오류

`stage_inventory`가 `git diff HEAD`만 사용해 미추적 backend migration을 누락했다. 이제 실행 소스 범위의 미추적 파일도 정확한 바이트 해시로 기록하고, 삭제된 파일은 `null`로 기록한다. 실제 현재 V22 migration이 `verification-17ddf5/final-source-inventory.json`의 overlay에 포함된다. 기존 생성 시점의 소스 기록은 수정하지 않았다.

`compare_replays`는 이전에 정규화 파일이 같고 두 상태 문자열이 성공이면 같은 디렉터리를 두 번 넣어도 새 DB 두 개의 재생으로 보고했다. 이제 실제 경로가 다른지, 관측된 DB 이름이 다른지, dataset/manifest/요청 이벤트 수가 같은지, 모든 요청 이벤트를 완료했는지, 검증 전후 DB fingerprint가 보존됐는지 확인한다. 기본 재생 호출은 요청한 package의 manifest digest도 비교한다. 이 관측은 backend 출력에 근거하며 별도의 외부 DB 검증이나 제품 승인으로 확대하지 않는다.

## 이번에 새로 확인한 결과

- 전체 DATA 회귀 87개 PASS, 실패/skip 0, 4.567초. 실제 loopback HTTP 검사는 호스트 권한으로 실행했다. 초기 sandbox 실행의 socket 제한 실패는 제품 오류로 보고하지 않는다.
- package-04의 패키지 항목 78,155개 전체 크기·SHA-256과 manifest digest를 33.897초에 다시 확인했다. bundle 파일 78,095개와 패키지 전체 항목 수는 서로 다른 집계다. manifest는 `sha256:4aa120ac66807f8052207f9b5da2733030795a2120510ef6cfe2df1bb09496d4`이며 원본 package를 수정하지 않았다.
- Docker 서버 27.3.1의 읽기 전용 응답을 확인했다. 이전 Docker 중단은 현재 차단 사유가 아니다.
- 실제 Git 임시 저장소 테스트로 수정·삭제·미추적·staged 파일의 출처 해시를 확인했다. 재생 테스트는 동일 경로/심볼릭 링크/복사된 DB 관측/미완료/실패/다른 manifest/DB drift/정규화 차이를 거절한다. 이 fixture 검사를 전체 제품 재생으로 표현하지 않는다.

## 이전 증거와 남은 실행

`admission-07/measurement.json`의 전체 bundle 입장 PASS와 `application-08/verification.json`의 로컬 적용·복원 PASS 파일을 다시 읽고 해시를 기록했다. 이 둘은 이번 액션에서 재실행한 결과가 아니다. `backend-blockers.json` 및 package-04의 admission 표시는 이전 시점 기록이며, 현재 Docker 상태나 새 입장/적용 결과를 대신하지 않는다.

`fixed-replays-05`는 첫 DB에서 18,396개 중 3,215개 처리 후 FAILED이며 둘째 실행은 없다. 따라서 두 전체 재생 및 5개 정규화 파일 비교는 여전히 미완료다. 부모가 기존 승인된 backend runner로 장시간 전체 재생을 담당한다. 새 lifecycle binding이나 harness 개발은 요청하지 않는다. 실패한 05는 보존하고 부모 실행은 새 출력 경로를 사용한다. 이번 실행자는 전체 재생을 시작하거나 프로세스를 남겨 두지 않았다.

재개 실행은 현재 backend의 자원 제한 runner와 현재 classpath를 사용하고, 원본 package 전체 checksum·실제 응답 부재에 대한 기록된 fault schedule·투명 압축·디스크 reserve를 유지해야 한다. 이번에 강화한 비교 함수가 실제 두 결과를 통과해야 한다. DATA 출처 보고서의 새 overlay에는 현재 미추적 V22까지 포함된다. backend 기본 HEAD만 보고 수정 코드를 이미 커밋한 것으로 표시하지 않는다.

상세 기계 판독 증거: `verification-17ddf5/verification.json`, `package-readback.json`, `final-source-inventory.json`, `tests.log`.

## 부모 장시간 실행용 classpath

지정한 `JAVA_HOME=/Users/ejunpark/.sdkman/candidates/java/current`으로 현재 Gradle `simulationDiagnosticClasspath`를 읽었다. 출력은 `docs/demo/verification-17ddf5/current-classpath.txt`이며 210개 항목이 모두 존재한다. 명령 exit code 0, stderr 0바이트다. 컴파일이나 backend 소스 변경은 수행하지 않았다. 정확한 경로와 SHA-256은 이번 envelope의 `classpath_preparation`에 있다. 부모는 기존 승인된 runner의 `--classpath` 인자로 이 파일을 사용할 수 있다.

삭제된 private clone/backup은 사용 가능한 입력으로 취급하지 않는다. 현재 대상의 backup/clone 갱신은 부모가 별도로 담당한다.
