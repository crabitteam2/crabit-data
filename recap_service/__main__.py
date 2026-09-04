"""Run the recap WSGI service with the standard-library server."""

from __future__ import annotations

import os
from wsgiref.simple_server import make_server

from .app import create_app


def main() -> None:
    host = os.environ.get("CRABIT_RECAP_HOST", "127.0.0.1")
    port = int(os.environ.get("CRABIT_RECAP_PORT", "8081"))
    with make_server(host, port, create_app()) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
