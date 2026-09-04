"""Run the recap WSGI service with the standard-library server."""

from __future__ import annotations

import json
import os
from wsgiref.simple_server import make_server

from .app import create_app


def main() -> None:
    host = os.environ.get("CRABIT_RECAP_HOST", "127.0.0.1")
    port = int(os.environ.get("CRABIT_RECAP_PORT", "8081"))
    with make_server(host, port, create_app()) as server:
        print(json.dumps({
            "event": "recap-service-ready",
            "host": host,
            "port": server.server_port,
            "url": f"http://{host}:{server.server_port}",
        }, ensure_ascii=False, separators=(",", ":"), sort_keys=True), flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
