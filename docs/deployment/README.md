# Recap service production image

이 디렉터리는 이미 확정된 `POST /internal/v1/recap-generations` 계약과 계산 로직을 바꾸지 않고
Python 서비스를 Staging과 Stable Demo의 private runtime에 배치하는 방법을 설명한다. Core production
연결, provider secret 생성·회전, VM rollout, DNS, TLS, merge와 release는 이 저장소 변경의 범위가
아니다. 이 저장소가 제공하는 publication workflow와 script는 immutable recap image를 만들고 Docker
Hub에서 그 identity를 다시 읽는 데까지만 책임진다. Workflow 실행과 registry write 자체는 별도
controller-bound action이 필요하다.

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

## Immutable image publication

`Publish Recap Image` (`.github/workflows/publish-recap-image.yml`)는 `workflow_dispatch`로만 실행하며
dispatch ref가 `main`이 아니면 실패한다. Checkout, unit/contract tests, compile, image build,
`verify-image.sh`, `verify-runtime.sh`, 정적 workflow 검증은 모두 event의 정확한 40자리 `GITHUB_SHA`를
대상으로 수행한다. Test를 마친 뒤에만 `dockerhub` environment의 `DOCKERHUB_USERNAME`과
`DOCKERHUB_TOKEN`으로 로그인한다. Credential 값은 파일, image, output 또는 summary에 기록하지 않는다.

Publication은 `crabitteam2/crabit-data:sha-<commit12>` 하나만 취급하고 `latest`, branch tag 또는 다른
mutable selector를 만들지 않는다. `publish-image.sh`는 BuildKit metadata의 tested config digest와 local
image identity를 먼저 고정한 뒤 다음처럼 fail closed한다.

- Tag 조회가 명시적인 `manifest unknown`이면 exact local image를 한 번 push한다.
- 인증 실패, timeout, 연결 오류 등 다른 조회 실패는 tag 부재로 해석하지 않으며 push하지 않는다.
- Tag가 이미 있으면 덮어쓰지 않고 그 tag를 한 번 resolve한 immutable digest만 검사한다.
- Push 실패는 부분 성공일 수 있으므로 같은 실행에서 재시도하지 않는다. 다음 controller action은 registry
  read-back으로 동일 image를 안전하게 채택할 수 있는지 먼저 확인해야 한다.
- 채택과 새 publication 모두 digest reference를 pull하고 single-platform `linux/amd64` manifest인지,
  manifest config digest가 tested config digest와 같은지, OCI revision이 dispatch된 전체 commit SHA와
  같은지, local `RepoDigests`에 그 immutable reference가 있는지 확인한다.

성공한 job output과 step summary에는 `image_digest`, fully qualified `image_reference`, `image_tag`,
`image_architecture`, `image_config_digest`, 전체 `image_revision`, `publication_result` (`published` 또는
`adopted`)가 남는다. 이 read-back이 Staging에서 선택할 수 있는 recap image evidence이며 workflow 성공
문구나 tag 존재만으로 digest identity를 추정하면 안 된다.

## Staging to Stable Demo rollout

Image publication 뒤의 provider 변경과 rollout은 이 repository workflow가 수행하지 않는다. 순서는 다음
경계를 유지한다.

1. Exact controller-bound provider action으로 `dockerhub` environment credential 이름과 protection을
   확인하거나 구성한다. Secret 값은 repository나 specialist evidence에 넣지 않는다.
2. Publication output의 digest, config digest, `linux/amd64`, 전체 crabit-data `main` revision을
   authoritative registry/workflow read-back으로 다시 확인한다.
3. Staging과 Stable Demo에 서로 다른 nonempty `CRABIT_RECAP_GENERATION_CREDENTIAL`과 required reviewer를
   controller-bound action으로 구성한다. Stable Demo의 `CRABIT_RECAP_IMAGE_DIGEST`는 아직 설정하지 않는다.
4. 기존 crabit-backend `Deploy Staging` workflow에 검증된 backend digest와 recap digest를 전달한다. 성공
   conclusion만 보지 말고 VM의 두 running `Config.Image`/`RepoDigest`, private recap isolation, public HTTPS,
   authenticated generation, database persistence와 owner retrieval, failure isolation, snapshot과 rollback
   readiness를 읽는다.
5. Staging evidence가 완전한 뒤 explicit promotion approval에서 멈춘다. 승인 후에만 같은 recap digest를
   Stable Demo 변수로 설정하고 exact backend release를 main으로 승격한다.
6. Stable Demo에서도 environment approval, registry identity, VM release pair, HTTPS, generation/storage/
   retrieval과 rollback 상태를 authoritative read-back한다. Core production activation은 이 절차에 포함되지
   않는다.

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
검증과 정적 workflow 검증만 수행하며 image를 push하지 않는다. `publish-recap-image.yml`도 cloud deploy,
live secret write 또는 application rollout을 수행하지 않는다. 실제 backend-to-Python generation, durable
storage, owner-only retrieval, restart persistence, failure isolation과 release-pair rollback은 sibling
`crabit-backend`의 two-image runtime verifier와 Staging authoritative read-back으로 증명한다.
