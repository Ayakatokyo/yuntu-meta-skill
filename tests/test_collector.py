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

    def test_collect_translates_specs_into_batch_and_rpa_parameters(self):
        captured = {}

        def fake_fetch_batch(**kwargs):
            captured.update(kwargs)
            return 0

        with tempfile.TemporaryDirectory() as directory, mock.patch.object(collector, "fetch_batch", fake_fetch_batch):
            status = collector.main([
                "collect", "--shop-id", "shop-1",
                "--query-spec", str(ROOT / "fixtures/query-spec.json"),
                "--highlight-spec", str(ROOT / "fixtures/highlight-spec.json"),
                "--output-dir", directory,
            ])
            query_file_exists = (Path(directory) / "resolved-query-spec.json").is_file()
            highlight_file_exists = (Path(directory) / "resolved-highlight-spec.json").is_file()

        self.assertEqual(status, 0)
        self.assertEqual(captured["shop_id"], "shop-1")
        self.assertEqual(captured["list_params"]["ranking_limit_type"], "CTR_TOP1000")
        self.assertEqual(captured["list_params"]["time_range_type"], "LAST_7_DAYS")
        self.assertEqual(captured["detail_date_params"], {"date_range_type": "LAST_7_DAYS"})
        self.assertEqual(captured["target_top_n"], 2)
        self.assertEqual(captured["candidate_top_n"], 4)
        self.assertEqual(captured["highlight_spec"]["metrics"]["点赞指数"]["strategy"], "absolute_max")
        self.assertTrue(query_file_exists)
        self.assertTrue(highlight_file_exists)


if __name__ == "__main__":
    unittest.main()
