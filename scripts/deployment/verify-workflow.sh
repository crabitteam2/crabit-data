#!/usr/bin/env bash
set -Eeuo pipefail

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly WORKFLOW="${ROOT}/.github/workflows/recap-service-ci.yml"
readonly CONTRACT_SHA256="ec93e480994203a6c8a62d5b9e9992627fba9b71ef346640ea7b80c38f62d233"
readonly TRANSPORT_SHA256="7772daae35b7b480328fc68e1df826575882c0d2f86cf49a3c05e24a26927457"
readonly DEVELOPMENT_ENTRYPOINT_SHA256="8ac3e4b10ce176fe342b49c6883850e380a2f60fdd828f3458eb41da6db93a6c"

sha256_file() {
	if command -v sha256sum >/dev/null 2>&1; then
		sha256sum "$1" | awk '{print $1}'
	else
		shasum -a 256 "$1" | awk '{print $1}'
	fi
}

[[ -f "${WORKFLOW}" ]] || { printf 'missing recap service CI workflow\n' >&2; exit 1; }
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

grep -q '^  pull_request:' "${WORKFLOW}"
grep -q '^  workflow_dispatch:' "${WORKFLOW}"
! grep -Eq '^  (push|pull_request_target|workflow_run|schedule):' "${WORKFLOW}"
grep -A1 '^permissions:' "${WORKFLOW}" | grep -q 'contents: read'
! grep -Eq 'id-token:[[:space:]]*write|docker[[:space:]]+push|gh[[:space:]]|gcloud[[:space:]]|kubectl[[:space:]]' "${WORKFLOW}"
grep -Fq 'python -m unittest discover -s tests -v' "${WORKFLOW}"
grep -Fq 'python -m compileall monthly_batch.py monthly_recap.py recap_presenter.py recap_service weekly_batch.py weekly_recap.py tests' "${WORKFLOW}"
grep -Fq 'docker build --build-arg "VCS_REF=${GITHUB_SHA}"' "${WORKFLOW}"
grep -Fq './scripts/deployment/verify-image.sh "${image}" "${GITHUB_SHA}"' "${WORKFLOW}"
grep -Fq './scripts/deployment/verify-runtime.sh "${image}"' "${WORKFLOW}"

if grep -RniE '(^|[^[:alnum:]_-])latest([^[:alnum:]_-]|$)|pull_request_target|set[[:space:]]+-x' \
		"${ROOT}/Dockerfile" \
		"${ROOT}/.github/workflows" \
		"${ROOT}/scripts/deployment/verify-image.sh" \
		"${ROOT}/scripts/deployment/verify-runtime.sh"; then
	printf 'forbidden floating image, privileged trigger, or debug tracing pattern found\n' >&2
	exit 1
fi

printf 'workflow verified: pull_request_only=true deploy=false pinned_base=true hashed_runtime_dependencies=true contract_bytes=preserved\n'
