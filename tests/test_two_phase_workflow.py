import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import collector
from scripts.analysis_facts import build_fact_index, load_selected_facts
from scripts.analysis_input import parse_analysis_input
from scripts.workflow_state import build_ready_receipt, get_workflow_status


ROOT = Path(__file__).resolve().parents[1]
REAL_RUN = ROOT / "runs/food-beverage-2026-0810-0820"


class TwoPhaseWorkflowTests(unittest.TestCase):
    def test_real_run_replay_rejects_brand_proxy_claims_from_audience_and_highlights(self):
        analysis_input = json.loads(
            (ROOT / "tests/fixtures/analysis-input-real.json").read_text(encoding="utf-8")
        )
        manifest = json.loads((REAL_RUN / "facts/manifest.json").read_text(encoding="utf-8"))
        spec = parse_analysis_input(
            analysis_input,
            {"status": "ready_for_analysis", "run_id": manifest["run_id"]},
            manifest,
        )
        selected = load_selected_facts(REAL_RUN, spec)
        fact_index = build_fact_index(selected)
        audience_ref = "facts/audience.json#/records/0"
        highlight_ref = "facts/highlight-frames.json#/records/0"

        for section, ref, brand in (
            ("audience", audience_ref, "燕之屋"),
            ("highlight_frames", highlight_ref, "小仙炖"),
        ):
            errors = collector.validate_analysis_result({
                "section": section,
                "findings": [{
                    "claim": f"{brand} 结论可直接指导投放",
                    "type": "fact",
                    "confidence": "high",
                    "fact_refs": [ref],
                }],
            }, fact_index)

            codes = {error["code"] for error in errors}
            self.assertIn("brand_proxy_requires_inference", codes)
            self.assertIn("brand_proxy_high_confidence", codes)
            self.assertIn("brand_proxy_explanation_required", codes)

    def test_real_run_replay_allows_non_brand_fact_on_proxy_record(self):
        analysis_input = json.loads(
            (ROOT / "tests/fixtures/analysis-input-real.json").read_text(encoding="utf-8")
        )
        manifest = json.loads((REAL_RUN / "facts/manifest.json").read_text(encoding="utf-8"))
        spec = parse_analysis_input(
            analysis_input,
            {"status": "ready_for_analysis", "run_id": manifest["run_id"]},
            manifest,
        )
        fact_index = build_fact_index(load_selected_facts(REAL_RUN, spec))

        errors = collector.validate_analysis_result({
            "section": "audience",
            "findings": [{
                "claim": "该事实记录包含人群标签",
                "type": "fact",
                "confidence": "high",
                "fact_refs": ["facts/audience.json#/records/0"],
            }],
        }, fact_index)

        self.assertEqual(errors, [])
    def test_real_run_phase_one_stops_at_ready_without_analysis_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            run_copy = Path(directory) / "run"
            shutil.copytree(REAL_RUN, run_copy)
            shutil.rmtree(run_copy / "analysis")
            summary_path = run_copy / "run-summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["status"] = "success"
            summary.pop("workflow", None)
            summary.pop("workflowStage", None)
            summary.pop("workflowProtocolVersion", None)
            summary_path.write_text(json.dumps(summary), encoding="utf-8")

            status = collector.main(["build-facts", "--run-dir", str(run_copy)])

            self.assertEqual(status, 0)
            self.assertEqual(get_workflow_status(run_copy)["status"], "ready_for_analysis")
            self.assertTrue(build_ready_receipt(run_copy)["ready_for_analysis"])
            self.assertFalse(list(run_copy.glob("**/*analysis-result*")))
            self.assertFalse(list(run_copy.glob("**/*.md")))

    def test_real_run_phase_two_handoff_and_response_use_fixture_without_recollecting(self):
        with tempfile.TemporaryDirectory() as directory:
            run_copy = Path(directory) / "run"
            shutil.copytree(REAL_RUN, run_copy)
            summary_path = run_copy / "run-summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["status"] = "success"
            summary.pop("workflow", None)
            summary.pop("workflowStage", None)
            summary.pop("workflowProtocolVersion", None)
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            collector.main(["build-facts", "--run-dir", str(run_copy)])

            request_output = run_copy / "analysis/phase-two.md"
            with mock.patch.object(collector, "fetch_batch") as fetch, \
                    mock.patch.object(collector, "build_fact_packages") as build:
                status = collector.main([
                    "analyze", "--run-dir", str(run_copy),
                    "--input", str(ROOT / "tests/fixtures/analysis-input-real.json"),
                    "--analysis-result", str(ROOT / "tests/fixtures/model-analysis-result-real.json"),
                    "--output", str(request_output),
                ])

            self.assertEqual(status, 0)
            self.assertFalse(fetch.called)
            self.assertFalse(build.called)
            request = json.loads(request_output.with_suffix(".model-analysis-request.json").read_text(encoding="utf-8"))
            self.assertEqual(request["request_type"], "yuntu_commercial_analysis")
            self.assertEqual(request["host_context"]["analysis_spec"]["business_question"], "比较 TOP4 素材榜单表现、人群差异与高光帧节奏，识别可验证的商业机会")
            self.assertEqual(set(request["host_context"]["facts"]), {
                "facts/material-ranking.json",
                "facts/audience.json",
                "facts/highlight-frames.json",
            })
            self.assertEqual(get_workflow_status(run_copy)["status"], "ready_for_analysis")
            result = json.loads(request_output.with_suffix(".analysis-result.json").read_text(encoding="utf-8"))
            self.assertTrue(all(
                finding["fact_refs"]
                for section in result["results"]
                for finding in section.get("findings", [])
            ))
            report = request_output.read_text(encoding="utf-8")
            self.assertIn("模型请求版本", report)
            self.assertIn("品牌代理识别", report)
    def test_real_run_is_ready_with_four_fact_packages_and_brand_coverage(self):
        receipt = build_ready_receipt(REAL_RUN)

        self.assertIn(receipt["status"], {"ready_for_analysis", "analysis_completed"})
        self.assertTrue(receipt["ready_for_analysis"] or receipt["status"] == "analysis_completed")
        self.assertEqual(receipt["coverage"]["ranking_records"], 1000)
        self.assertEqual(receipt["coverage"]["detail_records"], 4)
        self.assertEqual(receipt["coverage"]["highlight_materials"], 4)
        self.assertEqual(receipt["brand_classification"]["candidate_brands"], ["小仙炖", "燕之屋", "五个女博士"])
        self.assertEqual(receipt["brand_classification"]["unknown_count"], 306)
        self.assertEqual(set(receipt["fact_packages"]), {
            "material_ranking", "audience", "script", "highlight_frames",
        })

    def test_real_run_phase_two_reads_facts_only_and_preserves_fact_refs(self):
        with tempfile.TemporaryDirectory() as directory:
            run_copy = Path(directory) / "run"
            shutil.copytree(REAL_RUN, run_copy)
            output = run_copy / "analysis/phase-two.md"
            input_path = ROOT / "tests/fixtures/analysis-input-real.json"
            result_path = run_copy / "analysis/analysis.analysis-result.json"
            before_summary = (run_copy / "normalized/list-records.json").read_bytes()

            with mock.patch.object(collector, "fetch_batch") as fetch, \
                    mock.patch.object(collector, "build_fact_packages") as build:
                status = collector.main([
                    "analyze", "--run-dir", str(run_copy),
                    "--input", str(input_path),
                    "--analysis-result", str(result_path),
                    "--output", str(output),
                ])

            self.assertEqual(status, 0)
            self.assertFalse(fetch.called)
            self.assertFalse(build.called)
            self.assertEqual(before_summary, (run_copy / "normalized/list-records.json").read_bytes())
            self.assertEqual(get_workflow_status(run_copy)["status"], "ready_for_analysis")
            result = json.loads(output.with_suffix(".analysis-result.json").read_text(encoding="utf-8"))
            self.assertTrue(all(
                finding["fact_refs"]
                for section in result["results"]
                for finding in section.get("findings", [])
            ))
            report = output.read_text(encoding="utf-8")
            self.assertIn("source_empty", report)
            self.assertIn("品牌代理识别", report)
            self.assertIn("fact_refs", report)


if __name__ == "__main__":
    unittest.main()
