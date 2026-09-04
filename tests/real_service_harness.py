"""Reusable subprocess harness for cross-repository recap acceptance tests."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time
from typing import Iterator


@dataclass(frozen=True)
class RunningRecapService:
    base_url: str
    token: str
    process: subprocess.Popen[str]


def _startup_failure(process: subprocess.Popen[str], message: str) -> RuntimeError:
    assert process.stderr is not None
    detail = process.stderr.read().strip()
    return RuntimeError(message + (f": {detail}" if detail else ""))


def _await_ready(process: subprocess.Popen[str], timeout: float) -> dict:
    assert process.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("recap service did not announce readiness")
            if not selector.select(remaining):
                raise TimeoutError("recap service did not announce readiness")
            line = process.stdout.readline()
            if not line:
                raise _startup_failure(process, f"recap service exited before readiness (code={process.poll()})")
            try:
                message = json.loads(line)
            except json.JSONDecodeError as error:
                raise _startup_failure(process, f"recap service emitted invalid readiness JSON: {line.rstrip()}") from error
            if message.get("event") == "recap-service-ready":
                return message
    finally:
        selector.close()


@contextmanager
def running_recap_service(token: str = "acceptance-secret", timeout: float = 5.0) -> Iterator[RunningRecapService]:
    """Start the submitted WSGI service on an OS-assigned loopback port."""
    repository = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.update({
        "CRABIT_RECAP_HOST": "127.0.0.1",
        "CRABIT_RECAP_PORT": "0",
        "CRABIT_RECAP_TOKEN": token,
    })
    process = subprocess.Popen(
        [sys.executable, "-u", "-m", "recap_service"],
        cwd=repository,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        ready = _await_ready(process, timeout)
        yield RunningRecapService(ready["url"], token, process)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=timeout)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
