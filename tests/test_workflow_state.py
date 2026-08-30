import json
import tempfile
import unittest
from pathlib import Path

from scripts.workflow_state import (
    WorkflowStateError,
    build_ready_receipt,
    begin_model_analysis,
    complete_model_analysis,
    get_workflow_status,
    fail_model_analysis,
    set_stage,
)


class WorkflowStateTests(unittest.TestCase):
    def test_stage_progression_persists_without_dropping_existing_run_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "run-summary.json").write_text(
                json.dumps({"runId": "run-1", "status": "collecting", "custom": {"keep": True}}),
                encoding="utf-8",
            )

            set_stage(root, "collecting", source="pre_input")
            set_stage(root, "normalizing", normalized_count=3)
            set_stage(root, "fact_packaging", package_count=4)
            set_stage(root, "brand_classifying", candidate_brands=["品牌A"])
            current = set_stage(root, "ready_for_analysis", unknown_count=1)

            self.assertEqual(current["status"], "ready_for_analysis")
            persisted = json.loads((root / "run-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["custom"], {"keep": True})
            self.assertEqual(persisted["workflow"]["stage"], "ready_for_analysis")
            self.assertEqual(persisted["workflow"]["protocol_version"], "yuntu-two-phase-v1")
            self.assertEqual(len(persisted["workflow"]["history"]), 5)

    def test_stage_regression_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            set_stage(root, "normalizing")

            with self.assertRaises(WorkflowStateError):
                set_stage(root, "collecting")

    def test_failure_state_cannot_be_marked_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            set_stage(root, "collecting")
            set_stage(root, "failed", error="detail fetch failed")

            with self.assertRaises(WorkflowStateError):
                set_stage(root, "ready_for_analysis")
            status = get_workflow_status(root)
            self.assertEqual(status["status"], "failed")
            self.assertFalse(status["ready_for_analysis"])

    def test_completed_run_can_start_another_analysis_without_recollecting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            set_stage(root, "ready_for_analysis")
            set_stage(root, "analysis_running", analysis_id="analysis-1")
            set_stage(root, "analysis_completed", analysis_id="analysis-1")

            set_stage(root, "analysis_running", analysis_id="analysis-2")

            status = get_workflow_status(root)
            self.assertEqual(status["status"], "analysis_running")

    def test_model_analysis_helpers_persist_running_and_completed_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            set_stage(root, "ready_for_analysis")

            running = begin_model_analysis(root, "request-1")
            self.assertEqual(running["workflow"]["stage"], "analysis_running")
            self.assertEqual(running["workflow"]["metadata"]["request_id"], "request-1")

            result_path = root / "analysis.result.json"
            result_path.write_text("{}", encoding="utf-8")
            completed = complete_model_analysis(root, result_path)
            self.assertEqual(completed["workflow"]["stage"], "analysis_completed")
            self.assertEqual(completed["workflow"]["metadata"]["result_path"], str(result_path))

    def test_failed_model_analysis_returns_to_ready_for_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            set_stage(root, "ready_for_analysis")
            begin_model_analysis(root, "request-1")

            failed = fail_model_analysis(root, "request-1", "invalid response")

            self.assertEqual(failed["workflow"]["stage"], "ready_for_analysis")
            self.assertEqual(get_workflow_status(root)["status"], "ready_for_analysis")
            self.assertEqual(failed["workflow"]["metadata"]["error"], "invalid response")

    def test_ready_receipt_contains_coverage_packages_and_next_step(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "facts").mkdir()
            (root / "facts/manifest.json").write_text(json.dumps({
                "schema_version": 3,
                "run_id": "run-1",
                "brand_classification": {
                    "candidate_brands": ["品牌A"],
                    "unknown_count": 2,
                },
                "coverage": {
                    "ranking_records": 10,
                    "detail_records": 2,
                    "script_records": 2,
                    "highlight_materials": 2,
                    "available_highlight_frames": 8,
                },
                "packages": {
                    "material_ranking": {"path": "facts/material-ranking.json", "record_count": 0},
                    "audience": {"path": "facts/audience.json", "record_count": 0},
                    "script": {"path": "facts/script.json", "record_count": 0},
                    "highlight_frames": {"path": "facts/highlight-frames.json", "record_count": 0},
                },
            }), encoding="utf-8")
            for filename in ("material-ranking.json", "audience.json", "script.json", "highlight-frames.json"):
                (root / "facts" / filename).write_text(
                    json.dumps({"schema_version": 3, "records": []}), encoding="utf-8"
                )
            set_stage(root, "ready_for_analysis")

            receipt = build_ready_receipt(root)

            self.assertTrue(receipt["ready_for_analysis"])
            self.assertEqual(receipt["coverage"]["ranking_records"], 10)
            self.assertEqual(receipt["fact_packages"]["script"], "facts/script.json")
            self.assertEqual(receipt["brand_classification"]["unknown_count"], 2)
            self.assertIn("选择分析内容", receipt["next_step"])


if __name__ == "__main__":
    unittest.main()
