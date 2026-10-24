import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from population.publish import REQUIRED_FILES, publish_run


class PublishTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "generated"
        self.shared = self.root / "data"
        self.source.mkdir()
        self.shared.mkdir()
        for name in REQUIRED_FILES:
            (self.source / name).write_text("new snapshot")
        (self.source / "manifest.json").write_text(json.dumps({"schema_version": "1.0", "synthetic": True}))
        (self.shared / "processed/population").mkdir(parents=True)
        (self.shared / "processed/population/old.txt").write_text("old snapshot")

    def test_successful_build_publishes_all_artifacts(self):
        (self.shared / "build.py").write_text("from pathlib import Path\np=Path(__file__).parent/'database'\np.mkdir()\n(p/'shared.duckdb').write_text('built')\n")
        result = publish_run(self.source, self.shared)
        self.assertTrue(result.is_file())
        self.assertEqual(set(p.name for p in (self.shared / "processed/population").iterdir()), set(REQUIRED_FILES))
        self.assertFalse(list((self.shared / "processed").glob(".population-publish-*")))

    def test_failed_build_restores_previous_snapshot(self):
        (self.shared / "build.py").write_text("raise SystemExit(1)\n")
        with self.assertRaises(subprocess.CalledProcessError):
            publish_run(self.source, self.shared)
        self.assertEqual((self.shared / "processed/population/old.txt").read_text(), "old snapshot")
        self.assertFalse((self.shared / "processed/population/persons.parquet").exists())

    def test_incomplete_source_does_not_replace_existing_data(self):
        (self.shared / "build.py").write_text("raise RuntimeError('must not run')\n")
        (self.source / "persons.parquet").unlink()
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            publish_run(self.source, self.shared)
        self.assertTrue((self.shared / "processed/population/old.txt").exists())


if __name__ == "__main__":
    unittest.main()
