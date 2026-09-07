import hashlib
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = Path(
    os.environ.get(
        "CRABIT_BACKEND_OPENAPI",
        ROOT.parent / "crabit-backend" / "api" / "openapi.yaml",
    )
)
PROJECTION = ROOT / "api" / "feed-ranking-v1.yaml"
SYNC = ROOT / "scripts" / "recommendation" / "sync-feed-contract.py"


class FeedContractProjectionTest(unittest.TestCase):
    def test_projection_matches_canonical_backend_contract(self):
        self.assertTrue(CANONICAL.is_file(), f"paired canonical OpenAPI is required: {CANONICAL}")
        result = subprocess.run(
            [sys.executable, str(SYNC), str(CANONICAL), "--output", str(PROJECTION), "--check"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        digest = hashlib.sha256(CANONICAL.read_bytes()).hexdigest()
        self.assertIn(f"raw-byte-sha256: sha256:{digest}", PROJECTION.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
