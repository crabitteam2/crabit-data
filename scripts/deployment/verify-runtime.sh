#!/usr/bin/env bash
set -Eeuo pipefail

[[ "$#" == "1" ]] || {
	printf 'usage: verify-runtime.sh <local-recap-image>\n' >&2
	exit 2
}
readonly IMAGE="$1"
readonly TOKEN="verify_recap_generation_secret_32_chars"
readonly GENERATION_ID="00000000-0000-4000-8000-000000000901"
readonly CONTAINER="crabit-recap-verify-${$}"

for command in docker jq; do
	command -v "${command}" >/dev/null 2>&1 || {
		printf 'missing command: %s\n' "${command}" >&2
		exit 1
	}
done

tmp_dir="$(mktemp -d)"
container_id=""
cleanup() {
	if [[ -n "${container_id}" ]]; then
		docker rm -f "${container_id}" >/dev/null 2>&1 || true
	fi
	docker rm -f "${CONTAINER}-missing-token" >/dev/null 2>&1 || true
	rm -rf "${tmp_dir}"
}
trap cleanup EXIT

cat >"${tmp_dir}/runtime-client.py" <<'PY'
from __future__ import annotations

import http.client
import json
import os
import socket
import sys

from recap_service.app import REQUEST_LIMIT
from recap_service.json_codec import digest, response_bytes


GENERATION_ID = "00000000-0000-4000-8000-000000000901"


def generation_request() -> dict:
    request = {
        "schema_version": 1,
        "algorithm_version": "recap-1",
        "generation_id": GENERATION_ID,
        "input_digest": "",
        "student_id": "00000000-0000-4000-8000-000000000902",
        "card_balance_account_id": "00000000-0000-4000-8000-000000000903",
        "academy_id": "00000000-0000-4000-8000-000000000904",
        "kind": "WEEKLY",
        "period": {
            "start_date": "2026-08-24",
            "end_date_exclusive": "2026-08-31",
            "timezone": "Asia/Seoul",
        },
        "reference_date": "2026-08-30",
        "snapshot_at": "2026-08-31T00:00:00Z",
        "input": {
            "representative_wish_id": "00000000-0000-4000-8000-000000000905",
            "wishes": [{
                "wish_id": "00000000-0000-4000-8000-000000000905",
                "title": "runtime wish",
                "target_amount": 1500000,
                "created_at": "2026-08-16T00:00:00Z",
                "closed_at": None,
                "deleted_at": None,
                "status": "IN_PROGRESS",
                "is_representative": True,
                "saved_amount_at_period_end": 250000,
            }],
            "effective_transactions": [],
            "visit_metrics": {
                "received_visit_count": 0,
                "unique_received_visitor_count": 0,
                "previous_week_received_visit_count": 0,
                "monthly_outgoing_visit_count": 0,
            },
            "peer_metrics": {"habit_active_weeks": [], "achievement_rates": []},
            "success_story_candidates": [],
        },
    }
    digestable = {
        key: value for key, value in request.items()
        if key not in {"generation_id", "input_digest"}
    }
    request["input_digest"] = digest(digestable)
    return request


def request(method: str, path: str, body: bytes, headers: dict[str, str]):
    connection = http.client.HTTPConnection("127.0.0.1", 8081, timeout=5)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        payload = response.read()
        return response.status, dict(response.getheaders()), payload
    finally:
        connection.close()


def valid() -> None:
    body = response_bytes(generation_request())
    status, headers, payload = request("POST", "/internal/v1/recap-generations", body, {
        "Authorization": "Bearer " + os.environ["CRABIT_RECAP_TOKEN"],
        "Content-Type": "application/json",
        "Idempotency-Key": GENERATION_ID,
    })
    assert status == 200, status
    assert headers["Content-Type"] == "application/json"
    assert headers["Cache-Control"] == "no-store"
    assert int(headers["Content-Length"]) == len(payload)
    result = json.loads(payload)
    assert result["generation_id"] == GENERATION_ID
    assert result["schema_version"] == 1
    assert result["algorithm_version"] == "recap-1"
    assert result["kind"] == "WEEKLY"
    assert isinstance(result["view"], dict)
    sys.stdout.buffer.write(payload)


def invalid_auth() -> None:
    body = response_bytes(generation_request())
    status, headers, payload = request("POST", "/internal/v1/recap-generations", body, {
        "Authorization": "Bearer invalid-runtime-token",
        "Content-Type": "application/json",
        "Idempotency-Key": GENERATION_ID,
    })
    assert status == 401, status
    assert headers["WWW-Authenticate"] == "Bearer"
    assert headers["Cache-Control"] == "no-store"
    error = json.loads(payload)
    assert set(error) == {"code", "message", "retryable", "trace_id", "field_errors"}
    assert error["code"] == "AUTH_REQUIRED"
    assert not error["retryable"]


def no_http_health() -> None:
    status, headers, payload = request("GET", "/health", b"", {})
    assert status == 400, status
    assert headers["Cache-Control"] == "no-store"
    assert json.loads(payload)["code"] == "MALFORMED_REQUEST"


def declared_oversize() -> None:
    client = socket.create_connection(("127.0.0.1", 8081), timeout=5)
    try:
        client.sendall((
            "POST /internal/v1/recap-generations HTTP/1.0\r\n"
            "Host: 127.0.0.1\r\n"
            "Authorization: Bearer " + os.environ["CRABIT_RECAP_TOKEN"] + "\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {REQUEST_LIMIT + 1}\r\n"
            f"Idempotency-Key: {GENERATION_ID}\r\n"
            "\r\n"
        ).encode("ascii"))
        response = b""
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            response += chunk
    finally:
        client.close()
    status_line, _, payload = response.partition(b"\r\n")
    assert b" 413 " in status_line, status_line
    _, _, body = response.partition(b"\r\n\r\n")
    assert json.loads(body)["code"] == "PAYLOAD_TOO_LARGE"


commands = {
    "valid": valid,
    "invalid-auth": invalid_auth,
    "no-http-health": no_http_health,
    "declared-oversize": declared_oversize,
}
commands[sys.argv[1]]()
PY

if docker run --rm --name "${CONTAINER}-missing-token" \
		--network none --read-only --tmpfs /tmp:size=16m,mode=1777 \
		--user 10001:10001 --cap-drop ALL --security-opt no-new-privileges \
		"${IMAGE}" >"${tmp_dir}/missing-token.log" 2>&1; then
	printf 'production server started without CRABIT_RECAP_TOKEN\n' >&2
	exit 1
fi

container_id="$(docker run --detach --name "${CONTAINER}" \
	--read-only --tmpfs /tmp:size=64m,mode=1777 \
	--user 10001:10001 --cap-drop ALL --security-opt no-new-privileges \
	--pids-limit 64 --memory 768m --cpus 1 \
	--env CRABIT_RECAP_HOST=0.0.0.0 \
	--env CRABIT_RECAP_PORT=8081 \
	--env CRABIT_RECAP_TOKEN="${TOKEN}" \
	--env CRABIT_RECAP_WORKERS=2 \
	"${IMAGE}")"

for _ in $(seq 1 60); do
	if docker exec "${container_id}" python -c \
		"import socket; socket.create_connection(('127.0.0.1', 8081), 1).close()" \
		>/dev/null 2>&1; then
		break
	fi
	[[ "$(docker inspect "${container_id}" --format '{{.State.Running}}')" == "true" ]] || {
		docker logs "${container_id}" >&2 || true
		printf 'recap container exited before readiness\n' >&2
		exit 1
	}
	sleep 1
done
docker exec "${container_id}" python -c \
	"import socket; socket.create_connection(('127.0.0.1', 8081), 1).close()"

port_bindings="$(docker inspect "${container_id}" --format '{{json .HostConfig.PortBindings}}')"
[[ "${port_bindings}" == "null" || "${port_bindings}" == "{}" ]] || {
	printf 'recap runtime unexpectedly publishes a host port\n' >&2
	exit 1
}
[[ "$(docker inspect "${container_id}" --format '{{.Config.User}}')" == "10001:10001" ]]
[[ "$(docker inspect "${container_id}" --format '{{.HostConfig.ReadonlyRootfs}}')" == "true" ]]
[[ "$(docker inspect "${container_id}" --format '{{.HostConfig.Privileged}}')" == "false" ]]
docker inspect "${container_id}" --format '{{json .HostConfig.CapDrop}}' \
	| jq -e 'index("ALL") != null' >/dev/null
docker inspect "${container_id}" --format '{{json .HostConfig.SecurityOpt}}' \
	| jq -e 'index("no-new-privileges") != null or index("no-new-privileges:true") != null' >/dev/null
[[ "$(docker inspect "${container_id}" --format '{{.HostConfig.PidsLimit}}')" -eq 64 ]]
[[ "$(docker inspect "${container_id}" --format '{{.HostConfig.Memory}}')" -gt 0 ]]

docker exec -i "${container_id}" python - <<'PY'
from pathlib import Path

processes = []
for command_path in Path("/proc").glob("[0-9]*/cmdline"):
    try:
        command = command_path.read_bytes().replace(b"\0", b" ").decode("utf-8")
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        continue
    if "python -m gunicorn" in command:
        processes.append(command)
assert len(processes) == 3, len(processes)
PY

if docker exec "${container_id}" python -c \
		"from pathlib import Path; Path('/app/write-probe').write_text('forbidden')" \
		>/dev/null 2>&1; then
	printf 'read-only application filesystem accepted a write\n' >&2
	exit 1
fi
docker exec "${container_id}" python -c \
	"from pathlib import Path; p=Path('/tmp/write-probe'); p.write_text('ok'); assert p.read_text() == 'ok'; p.unlink()"

run_client() {
	local mode="$1"
	docker exec -i "${container_id}" python - "${mode}" <"${tmp_dir}/runtime-client.py"
}

run_client invalid-auth
run_client no-http-health
run_client declared-oversize
run_client valid >"${tmp_dir}/result-one.json"
run_client valid >"${tmp_dir}/result-two.json"
cmp -s "${tmp_dir}/result-one.json" "${tmp_dir}/result-two.json" || {
	printf 'identical recap requests produced different response bytes\n' >&2
	exit 1
}

docker logs "${container_id}" >"${tmp_dir}/runtime.log" 2>&1
for forbidden in "${TOKEN}" "${GENERATION_ID}" "runtime wish" 'student_id' 'input_digest'; do
	if grep -Fq "${forbidden}" "${tmp_dir}/runtime.log"; then
		printf 'runtime logs leaked request, result, or credential material\n' >&2
		exit 1
	fi
done

started_at="$(date +%s)"
docker stop --time 15 "${container_id}" >/dev/null
stopped_at="$(date +%s)"
[[ "$((stopped_at - started_at))" -le 20 ]] || {
	printf 'graceful shutdown exceeded 20 seconds\n' >&2
	exit 1
}
[[ "$(docker inspect "${container_id}" --format '{{.State.Status}}')" == "exited" ]]
[[ "$(docker inspect "${container_id}" --format '{{.State.ExitCode}}')" == "0" ]]

printf 'runtime verified: image=%s private_port=true non_root=true read_only=true production_workers=2 auth=closed payload_limit=closed deterministic=true graceful_shutdown=true\n' \
	"${IMAGE}"
