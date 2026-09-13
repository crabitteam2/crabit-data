"""Regression captured from a real local 100-student replay, event 3099."""
import json
from pathlib import Path
import unittest
from feed.ranking import rank
from feed_service.validation import validate

class NearTieTest(unittest.TestCase):
    def test_binary64_order_matches_independent_java_oracle(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/synthetic-data/feed-near-tie.json').read_text())
        self.assertEqual(fixture['expected'],rank(validate(fixture['request'])))
