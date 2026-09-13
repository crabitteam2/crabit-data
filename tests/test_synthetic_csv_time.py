import unittest
from datetime import datetime
import monthly_batch
import weekly_batch

class CsvTimeTest(unittest.TestCase):
    def test_existing_local_seconds_still_read(self):
        for module in (monthly_batch,weekly_batch):
            self.assertEqual(datetime(2026,6,1,12),module._parse_datetime('2026-06-01 12:00:00'))
            self.assertIsNone(module._parse_datetime(''))

    def test_actual_utc_export_retains_precision_and_korean_period_boundary(self):
        for module in (monthly_batch,weekly_batch):
            self.assertEqual(datetime(2026,6,1,0,0,0,123456),module._parse_datetime('2026-05-31T15:00:00.123456Z'))
            self.assertLess(module._parse_datetime('2026-06-01T03:00:00.000001Z'),module._parse_datetime('2026-06-01T03:00:00.000002Z'))
