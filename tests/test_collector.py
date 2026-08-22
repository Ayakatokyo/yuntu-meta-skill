import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import collector


ROOT = Path(__file__).resolve().parent


class CollectorTests(unittest.TestCase):
    def test_validate_prints_resolved_configuration_without_rpa(self):
        with tempfile.TemporaryDirectory() as directory:
            output = []
            with mock.patch("builtins.print", side_effect=lambda value: output.append(value)):
                status = collector.main([
                    "validate",
                    "--query-spec", str(ROOT / "fixtures/query-spec.json"),
                    "--highlight-spec", str(ROOT / "fixtures/highlight-spec.json"),
                ])
        self.assertEqual(status, 0)
        payload = json.loads(output[0])
        self.assertEqual(payload["query"]["collection"]["target_top_n"], 2)
        self.assertEqual(payload["highlights"]["metrics"]["点赞指数"]["strategy"], "absolute_max")

    def test_collector_has_no_analysis_or_report_commands(self):
        commands = collector._parser()._subparsers._group_actions[0].choices
        self.assertNotIn("render-report", commands)
        self.assertNotIn("prepare-analysis", commands)


if __name__ == "__main__":
    unittest.main()
