"""Reject copied, incomplete or differently bound results despite equal projections."""
import json
from pathlib import Path
import tempfile
import unittest

from synthetic_data.bundle import NORMALIZED
from synthetic_data.replay import compare_replays
from synthetic_data.validate import InvalidDataset


class ReplayEvidenceTest(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.first=Path(temporary.name)/'first'
        self.second=Path(temporary.name)/'second'
        for root,database in ((self.first,'simulation_first'),(self.second,'simulation_second')):
            root.mkdir()
            for name in NORMALIZED:
                (root/name).write_text('{"value":1}')
            self.write(root,dict(status='REPLAYED_PARTIAL_VALIDATION',requestedEvents=2,completedEvents=2,
                datasetId='sha256:'+'a'*64,manifestDigest='sha256:'+'b'*64,
                localDisposableDatabaseOnly=True,validationDatabaseUnchanged=True,
                validationPreservationBefore={'database':database},validationPreservationAfter={'database':database}))

    def write(self,root,observation):
        (root/'replay-observation.json').write_text(json.dumps(observation))

    def change_second(self,**changes):
        observation=json.loads((self.second/'replay-observation.json').read_text())
        observation.update(changes)
        self.write(self.second,observation)

    def test_distinct_completed_bound_replays_compare_all_five_outputs(self):
        result=compare_replays(self.first,self.second)
        self.assertEqual('PASS',result['status'])
        self.assertEqual(set(NORMALIZED),set(result['files']))
        self.assertEqual(['simulation_first','simulation_second'],result['databaseIdentities'])

    def test_same_directory_or_alias_is_not_two_runs(self):
        alias=self.second/'alias'
        alias.symlink_to(self.first,target_is_directory=True)
        for other in (self.first,alias):
            with self.subTest(other=other),self.assertRaisesRegex(InvalidDataset,'distinct-replay-directories'):
                compare_replays(self.first,other)

    def test_copy_of_one_database_is_not_two_runs(self):
        self.change_second(validationPreservationBefore={'database':'simulation_first'},
                           validationPreservationAfter={'database':'simulation_first'})
        with self.assertRaisesRegex(InvalidDataset,'distinct-replay-databases'):
            compare_replays(self.first,self.second)

    def test_incomplete_or_failed_run_is_not_a_pass(self):
        for change,rule in (({'completedEvents':1},'fixed-replay-complete'),
                            ({'status':'FAILED'},'fixed-replay-finished')):
            with self.subTest(change=change):
                self.change_second(**change)
                with self.assertRaisesRegex(InvalidDataset,rule):compare_replays(self.first,self.second)
                self.change_second(completedEvents=2,status='REPLAYED_PARTIAL_VALIDATION')

    def test_other_manifest_is_rejected_even_with_identical_files(self):
        self.change_second(manifestDigest='sha256:'+'c'*64)
        with self.assertRaisesRegex(InvalidDataset,'fixed-replay-input-binding'):
            compare_replays(self.first,self.second)

    def test_two_matching_runs_cannot_be_relabeled_as_another_manifest(self):
        with self.assertRaisesRegex(InvalidDataset,'fixed-replay-expected-manifest'):
            compare_replays(self.first,self.second,expected_manifest_digest='sha256:'+'d'*64)

    def test_database_drift_is_rejected(self):
        self.change_second(validationDatabaseUnchanged=False)
        with self.assertRaisesRegex(InvalidDataset,'fixed-replay-database-preservation'):
            compare_replays(self.first,self.second)

    def test_true_summary_flag_cannot_hide_changed_database_fingerprint(self):
        self.change_second(validationPreservationAfter={'database':'simulation_second','digest':'changed'})
        with self.assertRaisesRegex(InvalidDataset,'fixed-replay-database-preservation'):
            compare_replays(self.first,self.second)

    def test_normalized_difference_is_rejected(self):
        (self.second/NORMALIZED[-1]).write_text('{"value":2}')
        with self.assertRaisesRegex(InvalidDataset,'fixed-replay-equality'):
            compare_replays(self.first,self.second)
