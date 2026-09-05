#!/usr/bin/env bash
set -Eeuo pipefail

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly CI_WORKFLOW="${ROOT}/.github/workflows/recap-service-ci.yml"
readonly PUBLICATION_WORKFLOW="${ROOT}/.github/workflows/publish-recap-image.yml"
readonly PUBLISH_SCRIPT="${ROOT}/scripts/deployment/publish-image.sh"
readonly CONTRACT_SHA256="5b5afa7662e84c6809f167827125dd38a82b47fa437a2a8c9ba73c039ae083a5"
readonly TRANSPORT_SHA256="7772daae35b7b480328fc68e1df826575882c0d2f86cf49a3c05e24a26927457"
readonly DEVELOPMENT_ENTRYPOINT_SHA256="8ac3e4b10ce176fe342b49c6883850e380a2f60fdd828f3458eb41da6db93a6c"

sha256_file() {
	if command -v sha256sum >/dev/null 2>&1; then
		sha256sum "$1" | awk '{print $1}'
	else
		shasum -a 256 "$1" | awk '{print $1}'
	fi
}

[[ -f "${CI_WORKFLOW}" ]] || { printf 'missing recap service CI workflow\n' >&2; exit 1; }
[[ -f "${PUBLICATION_WORKFLOW}" ]] || { printf 'missing recap image publication workflow\n' >&2; exit 1; }
[[ -x "${PUBLISH_SCRIPT}" ]] || { printf 'missing executable recap image publication script\n' >&2; exit 1; }
for script in "${ROOT}"/scripts/deployment/*.sh; do
	bash -n "${script}"
done
python -m py_compile "${ROOT}/gunicorn.conf.py" "${ROOT}/recap_service/wsgi.py"

[[ "$(sha256_file "${ROOT}/api/recap-generation-v1.yaml")" == "${CONTRACT_SHA256}" ]] || {
	printf 'generation OpenAPI bytes changed\n' >&2
	exit 1
}
[[ "$(sha256_file "${ROOT}/recap_service/app.py")" == "${TRANSPORT_SHA256}" ]] || {
	printf 'WSGI transport bytes changed\n' >&2
	exit 1
}
[[ "$(sha256_file "${ROOT}/recap_service/__main__.py")" == "${DEVELOPMENT_ENTRYPOINT_SHA256}" ]] || {
	printf 'development entrypoint bytes changed\n' >&2
	exit 1
}

from_count="$(grep -Ec '^FROM python:3\.13\.7-slim-bookworm@sha256:[0-9a-f]{64}($|[[:space:]])' "${ROOT}/Dockerfile")"
[[ "${from_count}" == "2" ]] || {
	printf 'every Docker stage must use the approved digest-pinned Python base\n' >&2
	exit 1
}
grep -Fq 'USER 10001:10001' "${ROOT}/Dockerfile"
grep -Fq 'ENTRYPOINT ["python", "-m", "gunicorn"]' "${ROOT}/Dockerfile"
grep -Fq 'recap_service.wsgi:application' "${ROOT}/Dockerfile"
grep -Fq -- '--require-hashes' "${ROOT}/Dockerfile"
grep -Fq 'preload_app = True' "${ROOT}/gunicorn.conf.py"
grep -Fq 'accesslog = None' "${ROOT}/gunicorn.conf.py"
grep -Fq 'limit_request_line = 4094' "${ROOT}/gunicorn.conf.py"
grep -Fq 'max_requests = 1000' "${ROOT}/gunicorn.conf.py"

grep -q '^  pull_request:' "${CI_WORKFLOW}"
grep -q '^  workflow_dispatch:' "${CI_WORKFLOW}"
! grep -Eq '^  (push|pull_request_target|workflow_run|schedule):' "${CI_WORKFLOW}"
grep -A1 '^permissions:' "${CI_WORKFLOW}" | grep -q 'contents: read'
! grep -Eq 'id-token:[[:space:]]*write|docker[[:space:]]+push|gh[[:space:]]|gcloud[[:space:]]|kubectl[[:space:]]' "${CI_WORKFLOW}"
grep -Fq 'python -m unittest discover -s tests -v' "${CI_WORKFLOW}"
grep -Fq 'python -m compileall monthly_batch.py monthly_recap.py recap_presenter.py recap_service weekly_batch.py weekly_recap.py tests' "${CI_WORKFLOW}"
grep -Fq 'docker build --build-arg "VCS_REF=${GITHUB_SHA}"' "${CI_WORKFLOW}"
grep -Fq './scripts/deployment/verify-image.sh "${image}" "${GITHUB_SHA}"' "${CI_WORKFLOW}"
grep -Fq './scripts/deployment/verify-runtime.sh "${image}"' "${CI_WORKFLOW}"

grep -q '^  workflow_dispatch:' "${PUBLICATION_WORKFLOW}"
! grep -Eq '^  (push|pull_request|pull_request_target|workflow_run|schedule):' "${PUBLICATION_WORKFLOW}"
grep -A1 '^permissions:' "${PUBLICATION_WORKFLOW}" | grep -q 'contents: read'
! grep -Eq 'id-token:[[:space:]]*write|gh[[:space:]]|gcloud[[:space:]]|kubectl[[:space:]]|docker[[:space:]]+compose' "${PUBLICATION_WORKFLOW}"
! grep -Eq 'docker[[:space:]]+push' "${PUBLICATION_WORKFLOW}"
grep -Fq 'group: recap-image-publication-${{ github.sha }}' "${PUBLICATION_WORKFLOW}"
grep -A1 -F 'group: recap-image-publication-${{ github.sha }}' "${PUBLICATION_WORKFLOW}" \
	| grep -q 'cancel-in-progress: false'
grep -q 'environment: dockerhub' "${PUBLICATION_WORKFLOW}"
grep -Fq 'ref: ${{ github.sha }}' "${PUBLICATION_WORKFLOW}"
grep -q 'persist-credentials: false' "${PUBLICATION_WORKFLOW}"
grep -Fq '[[ "${GITHUB_REF}" == "refs/heads/main" ]]' "${PUBLICATION_WORKFLOW}"
grep -Fq '[[ "$(git rev-parse HEAD)" == "${GITHUB_SHA}" ]]' "${PUBLICATION_WORKFLOW}"
grep -Fq 'python -m unittest discover -s tests -v' "${PUBLICATION_WORKFLOW}"
grep -Fq -- 'docker build --provenance=false --platform linux/amd64' "${PUBLICATION_WORKFLOW}"
grep -Fq -- '--metadata-file "${RUNNER_TEMP}/tested-image-metadata.json"' "${PUBLICATION_WORKFLOW}"
grep -Fq './scripts/deployment/verify-image.sh "${image}" "${GITHUB_SHA}"' "${PUBLICATION_WORKFLOW}"
grep -Fq './scripts/deployment/verify-runtime.sh "${image}"' "${PUBLICATION_WORKFLOW}"
grep -q 'docker/login-action@v3' "${PUBLICATION_WORKFLOW}"
grep -q 'secrets.DOCKERHUB_USERNAME' "${PUBLICATION_WORKFLOW}"
grep -q 'secrets.DOCKERHUB_TOKEN' "${PUBLICATION_WORKFLOW}"
grep -Fq './scripts/deployment/publish-image.sh' "${PUBLICATION_WORKFLOW}"
grep -Fq '"${GITHUB_OUTPUT}"' "${PUBLICATION_WORKFLOW}"

test_step_line="$(grep -n -m1 -F -- '- name: Verify Python behavior and syntax' "${PUBLICATION_WORKFLOW}" | cut -d: -f1)"
build_step_line="$(grep -n -m1 -F -- '- name: Build and exercise the exact production image' "${PUBLICATION_WORKFLOW}" | cut -d: -f1)"
login_step_line="$(grep -n -m1 -F -- '- name: Authenticate to Docker Hub' "${PUBLICATION_WORKFLOW}" | cut -d: -f1)"
publish_step_line="$(grep -n -m1 -F -- '- name: Publish or adopt immutable recap tag' "${PUBLICATION_WORKFLOW}" | cut -d: -f1)"
[[ "${test_step_line}" -lt "${build_step_line}" \
	&& "${build_step_line}" -lt "${login_step_line}" \
	&& "${login_step_line}" -lt "${publish_step_line}" ]] || {
	printf 'publication workflow must test and build before registry authentication and publication\n' >&2
	exit 1
}

grep -Fq 'readonly IMAGE_REPOSITORY="crabitteam2/crabit-data"' "${PUBLISH_SCRIPT}"
grep -Fq 'readonly TAG="sha-${EXPECTED_REVISION:0:12}"' "${PUBLISH_SCRIPT}"
grep -Fq 'registry tag lookup failed; refusing to publish' "${PUBLISH_SCRIPT}"
grep -Fq 'registry push failed or is ambiguous; refusing to retry' "${PUBLISH_SCRIPT}"
grep -Fq 'local image does not match the tested build metadata' "${PUBLISH_SCRIPT}"
grep -Fq 'published digest is not a single-platform image manifest' "${PUBLISH_SCRIPT}"
grep -Fq 'published image does not match the locally tested image' "${PUBLISH_SCRIPT}"
grep -Fq 'published image revision does not match the dispatched revision' "${PUBLISH_SCRIPT}"
grep -Fq 'image_architecture=%s' "${PUBLISH_SCRIPT}"
grep -Fq 'docker pull "${immutable_image}"' "${PUBLISH_SCRIPT}"
grep -Fq 'docker manifest inspect "${immutable_image}"' "${PUBLISH_SCRIPT}"
[[ "$(grep -Ec 'docker[[:space:]]+push' "${PUBLISH_SCRIPT}")" -eq 1 ]] || {
	printf 'publication script must contain exactly one registry push operation\n' >&2
	exit 1
}

if grep -RniE '(^|[^[:alnum:]_-])latest([^[:alnum:]_-]|$)|pull_request_target|set[[:space:]]+-x' \
		"${ROOT}/Dockerfile" \
		"${ROOT}/.github/workflows" \
		"${ROOT}/scripts/deployment/publish-image.sh" \
		"${ROOT}/scripts/deployment/verify-image.sh" \
		"${ROOT}/scripts/deployment/verify-runtime.sh"; then
	printf 'forbidden floating image, privileged trigger, or debug tracing pattern found\n' >&2
	exit 1
fi

printf 'workflow verified: ci_push=false publication_manual_only=true publication_main_only=true deploy=false immutable_tag=true registry_readback=true pinned_base=true hashed_runtime_dependencies=true contract_bytes=preserved\n'
