import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.check_runtime_sync import check_runtime_sync


ROOT = Path(__file__).resolve().parents[1]


class RuntimeSyncTests(unittest.TestCase):
    def _copy_runtime(self, destination):
        shutil.copytree(ROOT / "scripts", destination / "scripts")
        shutil.copy2(ROOT / "SKILL.md", destination / "SKILL.md")

    def test_stale_skill_instructions_are_reported_as_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target"
            self._copy_runtime(target)
            (target / "SKILL.md").write_text("stale authentication instructions")
            result = check_runtime_sync(ROOT, target)
        self.assertFalse(result["ok"])
        self.assertIn("SKILL.md", result["mismatches"])

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
        self.assertEqual(
            result["files"]["scripts/analysis_spec.py"]["source_sha256"],
            result["files"]["scripts/analysis_spec.py"]["target_sha256"],
        )
        self.assertIn("scripts/model_analysis_request.py", result["files"])
        self.assertTrue(result["files"]["scripts/model_analysis_request.py"]["match"])

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
