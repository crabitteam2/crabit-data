"""Production WSGI entry point for the independently started feed service."""

import os

from .app import create_app

application = create_app(
    os.environ.get("FEED_RANKING_CREDENTIAL")
    or os.environ.get("CRABIT_FEED_RANKING_CREDENTIAL", "")
)
