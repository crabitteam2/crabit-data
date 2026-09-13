"""Compatibility entry point for the actual outcome-driven simulation CLI.

Example: python generate_data.py generate --backend ../crabit-backend --output docs/demo/artifacts/run-01
Legacy final-row fabrication is intentionally removed: generation requires the real local backend.
"""
from synthetic_data.__main__ import main

if __name__ == '__main__':
    main()
