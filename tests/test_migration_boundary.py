import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MigrationBoundaryTests(unittest.TestCase):
    def test_no_analysis_or_report_modules_are_shipped(self):
        names = {path.name for path in (ROOT / "scripts").glob("*.py")}
        self.assertFalse({"yuntu_analysis.py", "yuntu_report.py", "yuntu_presentation.py"} & names)
        source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "scripts").glob("*.py"))
        self.assertNotIn("yuntu_analysis", source)
        self.assertNotIn("yuntu_report", source)


if __name__ == "__main__":
    unittest.main()
