"""Run the feed endpoint with the standard-library WSGI server."""

import argparse
import json
import os
from wsgiref.simple_server import make_server

from .app import create_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8081")))
    args = parser.parse_args()
    credential = os.environ.get("FEED_RANKING_CREDENTIAL") or os.environ.get("CRABIT_FEED_RANKING_CREDENTIAL", "")
    with make_server(args.host, args.port, create_app(credential)) as server:
        print(json.dumps({"event": "feed-service-ready", "host": args.host, "port": server.server_port}, separators=(",", ":"), sort_keys=True), flush=True)
        server.serve_forever()


if __name__ == "__main__": main()
