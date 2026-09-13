import tempfile
from pathlib import Path
import unittest
from synthetic_data.storage import link_identical

class EvidenceStorageTest(unittest.TestCase):
    def test_both_original_paths_and_exact_bytes_survive_storage_sharing(self):
        with tempfile.TemporaryDirectory() as temporary:
            first,second=Path(temporary)/'raw.json',Path(temporary)/'captured.json'
            body=b'{"original_runtime_uuid":"abc","value":123}\n'
            first.write_bytes(body);second.write_bytes(body)
            self.assertEqual(len(body),link_identical(first,second))
            self.assertEqual(body,first.read_bytes());self.assertEqual(body,second.read_bytes())
            self.assertEqual(first.stat().st_ino,second.stat().st_ino)
            self.assertEqual(0,link_identical(first,second))

    def test_different_evidence_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            first,second=Path(temporary)/'raw.json',Path(temporary)/'captured.json'
            first.write_bytes(b'{"v":1}');second.write_bytes(b'{"v":2}')
            with self.assertRaisesRegex(ValueError,'differ'):link_identical(first,second)
            self.assertEqual(b'{"v":1}',first.read_bytes());self.assertEqual(b'{"v":2}',second.read_bytes())
