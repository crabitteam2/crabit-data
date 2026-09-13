"""Exercise source provenance against real isolated Git working tree states."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from synthetic_data.bundle import file_digest
from synthetic_data.provenance import backend_overlay
from synthetic_data.policy import digest


class BackendProvenanceTest(unittest.TestCase):
    def test_new_migration_modified_source_and_deleted_file_are_all_committed_by_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            def git(*args):
                return subprocess.check_output(['git','-c','core.hooksPath=/dev/null',
                    '-c','user.name=Fixture','-c','user.email=fixture@example.invalid',*args],cwd=root,stderr=subprocess.STDOUT)
            git('init','-q')
            source=root/'src/main/Existing.java';source.parent.mkdir(parents=True)
            source.write_text('old')
            deleted=root/'src/main/Removed.java';deleted.write_text('removed')
            git('add','.')
            git('-c','commit.gpgsign=false','commit','-qm','fixture')
            source.write_text('new')
            deleted.unlink()
            migration=root/'src/main/resources/db/migration/V22__new.sql'
            migration.parent.mkdir(parents=True);migration.write_text('SELECT 1;')
            (root/'unrelated.txt').write_text('not executable scope')
            overlay=backend_overlay(root)
            self.assertEqual({'src/main/Existing.java':file_digest(source),
                'src/main/Removed.java':None,
                'src/main/resources/db/migration/V22__new.sql':file_digest(migration)},overlay)
            old=digest(overlay)
            migration.write_text('SELECT 2;')
            self.assertNotEqual(old,digest(backend_overlay(root)))
            git('add',str(migration.relative_to(root)))
            self.assertIn(str(migration.relative_to(root)),backend_overlay(root))
