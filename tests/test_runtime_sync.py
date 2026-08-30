import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.check_runtime_sync import check_runtime_sync


ROOT = Path(__file__).resolve().parents[1]


class RuntimeSyncTests(unittest.TestCase):
    def _copy_runtime(self, destination):
        shutil.copytree(ROOT / "scripts", destination / "scripts")

    def test_matching_runtime_copy_and_help_are_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target"
            self._copy_runtime(target)

            result = check_runtime_sync(ROOT, target)

        self.assertTrue(result["ok"])
        self.assertEqual(result["mismatches"], [])
        self.assertTrue(result["help_contains_build_facts"])
        self.assertEqual(
            result["files"]["scripts/fact_packages.py"]["source_sha256"],
            result["files"]["scripts/fact_packages.py"]["target_sha256"],
        )

    def test_modified_runtime_file_is_reported_as_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target"
            self._copy_runtime(target)
            collector_path = target / "scripts" / "collector.py"
            collector_path.write_bytes(collector_path.read_bytes() + b"\n")

            result = check_runtime_sync(ROOT, target)

        self.assertFalse(result["ok"])
        self.assertIn("scripts/collector.py", result["mismatches"])


if __name__ == "__main__":
    unittest.main()
