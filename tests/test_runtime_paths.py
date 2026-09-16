from pathlib import Path
import sys
import tempfile
import unittest

from scripts.runtime_paths import RuntimePathError, SKILL_ROOT, external_runtime_path

sys.path.insert(0, str(SKILL_ROOT / "scripts"))
import collector  # noqa: E402


class RuntimePathTests(unittest.TestCase):
    def test_rejects_skill_internal_output(self):
        with self.assertRaisesRegex(RuntimePathError, "outside the skill installation"):
            external_runtime_path(SKILL_ROOT / "云图数据资源" / "new-run")

    def test_accepts_work_object_output(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "云图数据资源" / "new-run"
            self.assertEqual(external_runtime_path(target), target.absolute())

    def test_mutating_cli_rejects_skill_internal_run_before_writing(self):
        target = SKILL_ROOT / "云图数据资源" / "new-run"
        with self.assertRaises(SystemExit) as raised:
            collector.main(["build-facts", "--run-dir", str(target)])
        self.assertEqual(raised.exception.code, 2)
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
