# Recap service production image

이 디렉터리는 이미 확정된 `POST /internal/v1/recap-generations` 계약과 계산 로직을 바꾸지 않고
Python 서비스를 Staging과 Stable Demo의 private runtime에 배치하는 방법을 설명한다. Core production
연결, registry publication, provider secret 생성·회전, VM rollout, DNS, TLS, merge와 release는 이
저장소 변경의 범위가 아니다.

## Image identity and contents

`Dockerfile`의 모든 stage는 Python 3.13.7 slim Bookworm manifest digest에 고정되어 있다. 운영에 필요한
Gunicorn과 그 직접 의존성은 `recap_service/runtime-requirements.txt`의 버전과 wheel SHA-256으로
검증한 뒤 설치한다. 이미지는 다음 파일만 포함한다.

- 기존 recap 계산 모듈 `monthly_recap.py`, `weekly_recap.py`, `recap_presenter.py`
- 기존 transport와 validation을 포함한 `recap_service/`
- byte-identical `api/recap-generation-v1.yaml`
- bounded Gunicorn 설정

CSV 데이터, feed 추천 코드, batch entrypoint, 테스트, Git metadata와 로컬 환경 파일은 build context와
runtime image에서 제외한다. Build에는 정확한 40자리 commit SHA를 전달하고 이미지는 이를 OCI revision
label로 보존한다.

```bash
revision="$(git rev-parse HEAD)"
image="crabit-recap:sha-${revision:0:12}"
docker build --build-arg "VCS_REF=${revision}" --tag "${image}" .
./scripts/deployment/verify-image.sh "${image}" "${revision}"
```

배포와 rollback에는 mutable tag가 아니라 registry가 read-back한 fully qualified digest
`crabitteam2/crabit-data@sha256:<64 hex>`를 사용한다. Backend image digest와 recap image digest는 하나의
release pair로 함께 검증·승격·복구한다.

## Runtime boundary

Production entrypoint는 `python -m gunicorn`이며 application을 worker fork 전에 preload한다. 따라서
`CRABIT_RECAP_TOKEN`이 비어 있거나 application import가 실패하면 TCP socket을 healthy 상태로 노출하지
않는다. 기본 설정은 sync worker 2개, worker 최대 8개, thread 최대 4개, request/graceful timeout 최대
120초, worker당 1,000 request, bounded request line/header 수·크기다. Access log는 비활성화하여 Bearer
credential, 요청 snapshot, 생성 결과를 남기지 않는다.

필수 환경 변수:

- `CRABIT_RECAP_TOKEN`: backend의 `CRABIT_RECAP_GENERATION_CREDENTIAL`과 같은 nonempty runtime secret

선택 환경 변수:

- `CRABIT_RECAP_HOST` (기본 `0.0.0.0`), `CRABIT_RECAP_PORT` (기본 `8081`)
- `CRABIT_RECAP_WORKERS` (1..8), `CRABIT_RECAP_THREADS` (1..4)
- `CRABIT_RECAP_REQUEST_TIMEOUT_SECONDS` (1..120)
- `CRABIT_RECAP_GRACEFUL_TIMEOUT_SECONDS` (1..120)
- `CRABIT_RECAP_LOG_LEVEL` (기본 `info`)

Token은 repository, image layer, command argument, log 또는 HTTP health response에 넣지 않는다. Compose는
runtime environment로만 주입하며 recap 컨테이너에는 database, public ingress, frontend 또는 Demo token을
전달하지 않는다.

컨테이너는 UID/GID `10001:10001`, read-only root filesystem, writable 64 MiB `/tmp` tmpfs,
`no-new-privileges`로 실행한다. 8081은 private Compose network에 `expose`만 하고 host port mapping은 만들지
않는다. Readiness는 컨테이너 내부에서 8081 TCP accept만 확인한다. GET/HEAD health endpoint나 public
probe는 추가하지 않는다.

## Verification

`verify-runtime.sh`는 실제 production entrypoint로 이미지를 시작하여 다음을 확인한다.

- token 없는 preload 실패와 token 있는 TCP readiness
- numeric non-root user, read-only root, dropped capabilities, process/memory bounds
- 정확히 한 master와 두 worker, `/app` 쓰기 차단, `/tmp` 쓰기 허용
- invalid Bearer 401 challenge와 선언된 4 MiB 초과 request 413
- HTTP health route 부재
- 실제 authenticated weekly generation과 동일 입력의 byte-deterministic 결과
- access/error log에 credential, request identity, payload 또는 result가 남지 않음
- SIGTERM에 의한 bounded graceful shutdown과 exit code 0

```bash
./scripts/deployment/verify-runtime.sh "${image}"
./scripts/deployment/verify-workflow.sh
```

`recap-service-ci.yml`은 pull request와 수동 실행에서 unit/contract tests, compile, image build, image/runtime
검증과 정적 workflow 검증만 수행한다. Image push, cloud authentication, deploy 또는 live secret write는
하지 않는다. 실제 backend-to-Python generation, durable storage, owner-only retrieval, restart persistence,
failure isolation과 release-pair rollback은 sibling `crabit-backend`의 two-image runtime verifier에서 두 local
image를 함께 실행해 증명한다.
