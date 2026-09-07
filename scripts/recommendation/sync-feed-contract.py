#!/usr/bin/env python3
"""Generate or verify the Python feed OpenAPI projection from backend OpenAPI.

The parser is intentionally narrow: the backend document is the canonical source and
this tool only understands the stable x-feed-ranking-v1 fields and component blocks
needed by the Python-only transport. It uses no runtime dependency outside Python.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import sys


ROOT_SCHEMAS = ("request", "response", "error")


def _block(lines: list[str], start_pattern: str, indent: int) -> list[str]:
    pattern = re.compile(start_pattern)
    start = next((index for index, line in enumerate(lines) if pattern.fullmatch(line.rstrip("\n"))), None)
    if start is None:
        raise ValueError(f"missing canonical block: {start_pattern}")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.strip() and not line.lstrip().startswith("#"):
            current = len(line) - len(line.lstrip(" "))
            if current <= indent:
                end = index
                break
    return lines[start:end]


def _scalar(block: list[str], name: str, indent: int) -> str:
    pattern = re.compile(rf"^{{indent}}{re.escape(name)}:\s*[\"']?([^\"'\n]+)[\"']?\s*$".replace("{indent}", " " * indent))
    for line in block:
        match = pattern.match(line)
        if match:
            return match.group(1).strip()
    raise ValueError(f"missing canonical scalar: {name}")


def _schema_blocks(lines: list[str]) -> dict[str, list[str]]:
    schemas_start = next(
        (index for index, line in enumerate(lines) if line.rstrip("\n") == "  schemas:"),
        None,
    )
    if schemas_start is None:
        raise ValueError("missing canonical components.schemas")
    result: dict[str, list[str]] = {}
    index = schemas_start + 1
    while index < len(lines):
        line = lines[index]
        if line.strip() and len(line) - len(line.lstrip(" ")) < 4:
            break
        match = re.match(r"^    ([A-Za-z][A-Za-z0-9_]*):\s*$", line.rstrip("\n"))
        if not match:
            index += 1
            continue
        name = match.group(1)
        end = index + 1
        while end < len(lines):
            candidate = lines[end]
            if candidate.strip() and len(candidate) - len(candidate.lstrip(" ")) <= 4:
                break
            end += 1
        result[name] = lines[index:end]
        index = end
    return result


def _referenced_schemas(roots: list[str], schemas: dict[str, list[str]]) -> list[str]:
    ordered: list[str] = []
    pending = list(roots)
    while pending:
        name = pending.pop(0)
        if name in ordered:
            continue
        if name not in schemas:
            raise ValueError(f"canonical schema is missing: {name}")
        ordered.append(name)
        text = "".join(schemas[name])
        for reference in re.findall(r"#/components/schemas/([A-Za-z][A-Za-z0-9_]*)", text):
            if reference not in ordered and reference not in pending:
                pending.append(reference)
    return ordered


def _assert_conditionals(schemas: dict[str, list[str]]) -> None:
    required_fragments = {
        "FeedMonthMetrics": (
            "coverage: {const: COMPLETE}",
            "values: {$ref: '#/components/schemas/FeedCoreMetrics'}",
            "values: {type: \"null\"}",
        ),
        "FeedRankingCandidate": (
            "state: {const: COMPLETED}",
            "closed_at: {type: string, format: date-time}",
            "closed_at: {type: \"null\"}",
        ),
        "FeedRankingError": (
            "code: {const: RANKING_UNAVAILABLE}",
            "retryable: {const: true}",
            "retryable: {const: false}",
        ),
    }
    for name, fragments in required_fragments.items():
        text = "".join(schemas.get(name, []))
        missing = [fragment for fragment in fragments if fragment not in text]
        if missing:
            raise ValueError(f"canonical {name} conditional is incomplete: {missing}")


def render(canonical_bytes: bytes) -> bytes:
    try:
        canonical = canonical_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("canonical OpenAPI must be UTF-8") from error
    lines = canonical.splitlines(keepends=True)
    extension = _block(lines, r"x-feed-ranking-v1:", 0)
    transport = _block(extension, r"  rankingTransport:", 2)
    method = _scalar(transport, "method", 4).lower()
    path = _scalar(transport, "path", 4)
    schema_section = _block(transport, r"    schemas:", 4)
    roots = [_scalar(schema_section, role, 6).rsplit("/", 1)[-1] for role in ROOT_SCHEMAS]
    status_section = _block(transport, r"      statuses:", 6)
    statuses: list[tuple[str, str]] = []
    for line in status_section[1:]:
        match = re.match(r'^        ["\']([0-9]{3})["\']:\s*["\']([^"\']+)["\']\s*$', line.rstrip("\n"))
        if match:
            statuses.append((match.group(1), match.group(2)))
    if not statuses:
        raise ValueError("canonical ranking transport has no status mapping")

    schemas = _schema_blocks(lines)
    names = _referenced_schemas(roots, schemas)
    _assert_conditionals(schemas)
    digest = hashlib.sha256(canonical_bytes).hexdigest()
    extension_digest = hashlib.sha256("".join(extension).encode("utf-8")).hexdigest()

    output = [
        "# Generated by scripts/recommendation/sync-feed-contract.py; do not hand-edit.\n",
        "openapi: 3.1.0\n",
        "info:\n",
        "  title: Crabit internal feed ranking contract\n",
        "  version: feed-ranking-v1\n",
        "x-canonical-source:\n",
        "  repository: crabit-backend\n",
        "  path: api/openapi.yaml\n",
        f"  raw-byte-sha256: sha256:{digest}\n",
        "  extension: x-feed-ranking-v1\n",
        f"  extension-raw-sha256: sha256:{extension_digest}\n",
        "paths:\n",
        f"  {path}:\n",
        f"    {method}:\n",
        "      security: [{feedBearer: []}]\n",
        "      requestBody:\n",
        "        required: true\n",
        "        content:\n",
        f"          application/json: {{schema: {{$ref: '#/components/schemas/{roots[0]}'}}}}\n",
        "      responses:\n",
        "        '200':\n",
        "          description: Deterministic feed-rules-v1 ranking\n",
        f"          content: {{application/json: {{schema: {{$ref: '#/components/schemas/{roots[1]}'}}}}}}\n",
    ]
    for status, code in statuses:
        output.append(
            f"        '{status}': {{description: {code}, content: {{application/json: {{schema: {{$ref: '#/components/schemas/{roots[2]}'}}}}}}}}\n"
        )
    output.extend(
        [
            "components:\n",
            "  securitySchemes:\n",
            "    feedBearer: {type: http, scheme: bearer}\n",
            "  schemas:\n",
        ]
    )
    for name in names:
        output.extend(schemas[name])
    return "".join(output).encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("canonical", type=Path, help="canonical crabit-backend api/openapi.yaml")
    parser.add_argument("--output", type=Path, default=Path("api/feed-ranking-v1.yaml"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render(args.canonical.read_bytes())
    if args.check:
        actual = args.output.read_bytes() if args.output.is_file() else b""
        if actual != expected:
            print(
                f"feed contract projection is stale; run {Path(__file__).name} {args.canonical} --output {args.output}",
                file=sys.stderr,
            )
            return 1
        print(f"feed contract parity verified: {args.output} <- {args.canonical}")
        return 0
    args.output.write_bytes(expected)
    print(f"generated {args.output} from {args.canonical}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
