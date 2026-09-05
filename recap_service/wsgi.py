"""Production WSGI application loaded and validated before workers start."""

from .app import create_app


application = create_app()
