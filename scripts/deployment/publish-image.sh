#!/usr/bin/env bash
set -Eeuo pipefail

[[ "$#" == "3" ]] || {
	printf 'usage: publish-image.sh <40-char-revision> <build-metadata-json> <output-file>\n' >&2
	exit 2
}

readonly EXPECTED_REVISION="$1"
readonly METADATA_FILE="$2"
readonly OUTPUT_FILE="$3"
readonly IMAGE_REPOSITORY="crabitteam2/crabit-data"
readonly TAG="sha-${EXPECTED_REVISION:0:12}"
readonly LOCAL_IMAGE="crabit-recap:${TAG}"
readonly TAGGED_IMAGE="${IMAGE_REPOSITORY}:${TAG}"

[[ "${EXPECTED_REVISION}" =~ ^[0-9a-f]{40}$ ]] || {
	printf 'invalid expected revision\n' >&2
	exit 2
}
[[ -f "${METADATA_FILE}" ]] || {
	printf 'missing build metadata\n' >&2
	exit 2
}
[[ -n "${OUTPUT_FILE}" ]] || {
	printf 'missing output file\n' >&2
	exit 2
}
for command in docker grep jq sed tar; do
	command -v "${command}" >/dev/null 2>&1 || {
		printf 'missing command: %s\n' "${command}" >&2
		exit 1
	}
done

local_manifest_digest="$(jq -r '.["containerimage.digest"] // empty' "${METADATA_FILE}")"
local_config_digest="$(jq -r '.["containerimage.config.digest"] // empty' "${METADATA_FILE}")"
[[ "${local_manifest_digest}" =~ ^sha256:[0-9a-f]{64}$ \
	&& "${local_config_digest}" =~ ^sha256:[0-9a-f]{64}$ ]] || {
	printf 'local tested image identity is invalid\n' >&2
	exit 1
}
[[ "$(docker image inspect "${LOCAL_IMAGE}" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')" == "${EXPECTED_REVISION}" ]] || {
	printf 'local image revision does not match the dispatched revision\n' >&2
	exit 1
}
[[ "$(docker image inspect "${LOCAL_IMAGE}" --format '{{.Os}}/{{.Architecture}}')" == "linux/amd64" ]] || {
	printf 'local image must be linux/amd64\n' >&2
	exit 1
}
if ! local_config_path="$(
	docker image save "${LOCAL_IMAGE}" \
		| tar -xOf - manifest.json \
		| jq -er 'if length == 1 and (.[0].Config | type == "string") then .[0].Config else error("ambiguous image archive") end'
)"; then
	printf 'local image config identity could not be read\n' >&2
	exit 1
fi
local_config_name="${local_config_path##*/}"
local_config_hex="${local_config_name%.json}"
[[ "${local_config_hex}" =~ ^[0-9a-f]{64}$ \
	&& "sha256:${local_config_hex}" == "${local_config_digest}" ]] || {
	printf 'local image does not match the tested build metadata\n' >&2
	exit 1
}

extract_digest() {
	local output="$1"
	local resolved
	resolved="$(printf '%s\n' "${output}" | sed -nE 's/.*[Dd]igest: (sha256:[0-9a-f]{64})([[:space:]].*)?$/\1/p')"
	[[ "${resolved}" =~ ^sha256:[0-9a-f]{64}$ && "${resolved}" != *$'\n'* ]] || {
		printf 'registry digest read-back failed\n' >&2
		return 1
	}
	printf '%s\n' "${resolved}"
}

publication_result="adopted"
if pull_output="$(docker pull "${TAGGED_IMAGE}" 2>&1)"; then
	digest="$(extract_digest "${pull_output}")"
elif printf '%s\n' "${pull_output}" | grep -Eiq 'manifest unknown|manifest for [^[:space:]]+ not found'; then
	publication_result="published"
	docker tag "${LOCAL_IMAGE}" "${TAGGED_IMAGE}"
	if ! push_output="$(docker push "${TAGGED_IMAGE}" 2>&1)"; then
		printf '%s\n' "${push_output}" >&2
		printf 'registry push failed or is ambiguous; refusing to retry\n' >&2
		exit 1
	fi
	digest="$(extract_digest "${push_output}")"
else
	printf '%s\n' "${pull_output}" >&2
	printf 'registry tag lookup failed; refusing to publish\n' >&2
	exit 1
fi

readonly digest
readonly immutable_image="${IMAGE_REPOSITORY}@${digest}"
docker pull "${immutable_image}" >/dev/null
manifest="$(docker manifest inspect "${immutable_image}")"
media_type="$(jq -r '.mediaType // empty' <<< "${manifest}")"
case "${media_type}" in
	application/vnd.docker.distribution.manifest.v2+json|application/vnd.oci.image.manifest.v1+json) ;;
	*) printf 'published digest is not a single-platform image manifest\n' >&2; exit 1 ;;
esac

registry_config_digest="$(jq -r '.config.digest // empty' <<< "${manifest}")"
[[ "${registry_config_digest}" == "${local_config_digest}" ]] || {
	printf 'published image does not match the locally tested image\n' >&2
	exit 1
}
[[ "$(docker image inspect "${immutable_image}" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')" == "${EXPECTED_REVISION}" ]] || {
	printf 'published image revision does not match the dispatched revision\n' >&2
	exit 1
}
architecture="$(docker image inspect "${immutable_image}" --format '{{.Os}}/{{.Architecture}}')"
[[ "${architecture}" == "linux/amd64" ]] || {
	printf 'published image must be linux/amd64\n' >&2
	exit 1
}
docker image inspect "${immutable_image}" --format '{{json .RepoDigests}}' \
	| jq -e --arg expected "${immutable_image}" 'index($expected) != null' >/dev/null || {
	printf 'immutable registry digest is absent from pulled image metadata\n' >&2
	exit 1
}

{
	printf 'image_digest=%s\n' "${digest}"
	printf 'image_reference=%s\n' "${immutable_image}"
	printf 'image_tag=%s\n' "${TAG}"
	printf 'image_architecture=%s\n' "${architecture}"
	printf 'image_config_digest=%s\n' "${registry_config_digest}"
	printf 'image_revision=%s\n' "${EXPECTED_REVISION}"
	printf 'publication_result=%s\n' "${publication_result}"
} >> "${OUTPUT_FILE}"

printf 'recap image %s: tag=%s digest=%s config=%s architecture=%s revision=%s\n' \
	"${publication_result}" "${TAG}" "${digest}" "${registry_config_digest}" \
	"${architecture}" "${EXPECTED_REVISION}"
