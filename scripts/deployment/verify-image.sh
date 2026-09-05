#!/usr/bin/env bash
set -Eeuo pipefail

[[ "$#" == "2" ]] || {
	printf 'usage: verify-image.sh <image> <40-char-revision>\n' >&2
	exit 2
}
readonly IMAGE="$1"
readonly EXPECTED_REVISION="$2"
readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly CONTRACT_PATH="app/api/recap-generation-v1.yaml"

[[ "${EXPECTED_REVISION}" =~ ^[0-9a-f]{40}$ ]] || {
	printf 'invalid expected revision\n' >&2
	exit 2
}
for command in docker jq tar; do
	command -v "${command}" >/dev/null 2>&1 || {
		printf 'missing command: %s\n' "${command}" >&2
		exit 1
	}
done

user="$(docker image inspect "${IMAGE}" --format '{{.Config.User}}')"
[[ "${user}" == "10001:10001" ]] || {
	printf 'image user must be 10001:10001\n' >&2
	exit 1
}
[[ "$(docker image inspect "${IMAGE}" --format '{{.Config.WorkingDir}}')" == "/app" ]] || {
	printf 'image working directory must be /app\n' >&2
	exit 1
}
[[ "$(docker image inspect "${IMAGE}" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')" == "${EXPECTED_REVISION}" ]] || {
	printf 'OCI revision label mismatch\n' >&2
	exit 1
}
[[ "$(docker image inspect "${IMAGE}" --format '{{index .Config.Labels "org.opencontainers.image.source"}}')" == "https://github.com/crabitteam2/crabit-data" ]] || {
	printf 'OCI source label mismatch\n' >&2
	exit 1
}
docker image inspect "${IMAGE}" --format '{{json .Config.ExposedPorts}}' \
	| jq -e 'keys == ["8081/tcp"]' >/dev/null || {
		printf 'image must expose only 8081/tcp\n' >&2
		exit 1
	}
docker image inspect "${IMAGE}" --format '{{json .Config.Entrypoint}}' \
	| jq -e '. == ["python", "-m", "gunicorn"]' >/dev/null || {
		printf 'image entrypoint must be Gunicorn\n' >&2
		exit 1
	}
docker image inspect "${IMAGE}" --format '{{json .Config.Cmd}}' \
	| jq -e '. == ["--config", "/app/gunicorn.conf.py", "recap_service.wsgi:application"]' >/dev/null || {
		printf 'image command must load the production recap WSGI application\n' >&2
		exit 1
	}
docker image inspect "${IMAGE}" --format '{{json .Config.Env}}' \
	| jq -e 'all(.[]; test("^CRABIT_.*(TOKEN|CREDENTIAL|PASSWORD|SECRET)=") | not)' >/dev/null || {
		printf 'image config contains a credential-bearing environment value\n' >&2
		exit 1
	}

tmp_dir="$(mktemp -d)"
container_id=""
cleanup() {
	if [[ -n "${container_id}" ]]; then
		docker rm -f "${container_id}" >/dev/null 2>&1 || true
	fi
	rm -rf "${tmp_dir}"
}
trap cleanup EXIT

container_id="$(docker create "${IMAGE}")"
docker export "${container_id}" --output "${tmp_dir}/rootfs.tar"
tar -xf "${tmp_dir}/rootfs.tar" -C "${tmp_dir}" \
	"${CONTRACT_PATH}" \
	app/gunicorn.conf.py \
	app/recap_service/app.py \
	app/recap_service/wsgi.py
cmp -s "${ROOT}/api/recap-generation-v1.yaml" "${tmp_dir}/${CONTRACT_PATH}" || {
	printf 'packaged generation OpenAPI bytes do not match the repository contract\n' >&2
	exit 1
}
cmp -s "${ROOT}/gunicorn.conf.py" "${tmp_dir}/app/gunicorn.conf.py" || {
	printf 'packaged Gunicorn configuration does not match the repository\n' >&2
	exit 1
}
cmp -s "${ROOT}/recap_service/app.py" "${tmp_dir}/app/recap_service/app.py" || {
	printf 'packaged WSGI transport does not match the repository\n' >&2
	exit 1
}
cmp -s "${ROOT}/recap_service/wsgi.py" "${tmp_dir}/app/recap_service/wsgi.py" || {
	printf 'packaged production application does not match the repository\n' >&2
	exit 1
}

if tar -tf "${tmp_dir}/rootfs.tar" | awk '
	/^app\/(tests|data|feed|\.git)(\/|$)/ { found = 1 }
	/^app\/(generate_data|monthly_batch|weekly_batch|wish_category_classifier)\.py$/ { found = 1 }
	/^app\/.*(^|\/)(\.env($|\.)|.*\.(key|pem)$)/ { found = 1 }
	/^app\/.*(__pycache__|\.py[co]$)/ { found = 1 }
	END { exit(found ? 0 : 1) }
'; then
	printf 'runtime filesystem contains excluded data, tests, cache, env, or key material\n' >&2
	exit 1
fi

image_id="$(docker image inspect "${IMAGE}" --format '{{.Id}}')"
printf 'image verified: image=%s id=%s revision=%s user=%s contract_sha256=%s\n' \
	"${IMAGE}" "${image_id}" "${EXPECTED_REVISION}" "${user}" \
	"$(sha256sum "${ROOT}/api/recap-generation-v1.yaml" 2>/dev/null | awk '{print $1}' || shasum -a 256 "${ROOT}/api/recap-generation-v1.yaml" | awk '{print $1}')"
