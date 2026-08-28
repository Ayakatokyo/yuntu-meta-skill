import json
import io
import tempfile
import unittest
from contextlib import redirect_stderr
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
        self.assertEqual(payload["highlights"]["metrics"]["点赞指数"]["strategy"], "top_values")

    def test_collector_has_no_analysis_or_report_commands(self):
        commands = collector._parser()._subparsers._group_actions[0].choices
        self.assertNotIn("render-report", commands)
        self.assertNotIn("prepare-analysis", commands)

    def test_build_facts_dispatches_to_local_builder(self):
        captured = {}

        def fake_build_fact_packages(run_dir):
            captured["run_dir"] = run_dir
            return {
                "packages": {
                    "material_ranking": {"record_count": 2},
                    "audience": {"record_count": 2},
                    "script": {"record_count": 1},
                    "highlight_frames": {"record_count": 1},
                },
                "coverage": {
                    "ranking_records": 2,
                    "detail_records": 1,
                    "script_records": 1,
                    "highlight_materials": 1,
                    "available_highlight_frames": 1,
                },
            }

        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(collector, "build_fact_packages", fake_build_fact_packages), \
                mock.patch("builtins.print") as printer:
            status = collector.main(["build-facts", "--run-dir", directory])

        self.assertEqual(status, 0)
        self.assertEqual(captured["run_dir"], directory)
        output = json.loads(printer.call_args.args[0])
        self.assertEqual(output["manifest_path"], str(Path(directory) / "facts/manifest.json"))
        self.assertEqual(output["coverage"]["ranking_records"], 2)

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
        self.assertEqual(captured["candidate_top_n"], 1000)
        self.assertEqual(captured["highlight_spec"]["metrics"]["点赞指数"]["strategy"], "top_values")
        self.assertTrue(query_file_exists)
        self.assertTrue(highlight_file_exists)

    def test_retry_highlights_uses_the_saved_spec_without_a_shop_id(self):
        captured = {}

        def fake_retry_highlights_batch(**kwargs):
            captured.update(kwargs)
            return 0

        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(collector, "_load_saved_specs", return_value=({}, {"metrics": {}})), \
                mock.patch.object(
                    collector, "retry_highlights_batch", fake_retry_highlights_batch
                ):
            status = collector.main([
                "retry-highlights", "--output-dir", directory,
            ])

        self.assertEqual(status, 0)
        self.assertEqual(captured, {
            "output_dir": directory,
            "highlight_spec": {"metrics": {}},
        })

    def test_retry_highlights_rejects_a_saved_spec_with_the_wrong_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "resolved-query-spec.json").write_text(
                (ROOT / "fixtures/query-spec.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (root / "resolved-highlight-spec.json").write_text(
                (ROOT / "fixtures/highlight-spec.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (root / "run-summary.json").write_text(json.dumps({
                "collectionContract": {"configurationFingerprint": "0" * 64},
            }), encoding="utf-8")
            with mock.patch.object(collector, "retry_highlights_batch") as retry:
                with redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        collector.main(["retry-highlights", "--output-dir", directory])

        self.assertEqual(raised.exception.code, 2)
        retry.assert_not_called()


if __name__ == "__main__":
    unittest.main()
