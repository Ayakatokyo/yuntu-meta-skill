import json
import shutil
import tempfile
from pathlib import Path

from scripts import collector
from scripts.analysis_workflow import (
    apply_fact_selection_result,
    prepare_fact_selection_handoff,
    prepare_model_analysis_handoff,
)
from scripts.fact_selection import FactPackage
from scripts.workflow_state import get_workflow_status


ROOT = Path(__file__).resolve().parents[1]
REAL_RUN = ROOT / "runs/food-beverage-2026-0810-0820"


def _selection_result(run_id):
    return {
        "intent": {
            "business_question": "找出曝光高但转化差的素材",
            "objectives": ["find_high_exposure_low_conversion"],
            "metrics": ["show_cnt", "cvr"],
            "dimensions": ["brand"],
            "required_packages": ["material_ranking", "script"],
            "material_scope": None,
            "creative_analysis_required": False,
        },
        "selection_spec": {
            "packages": ["material_ranking", "script"],
            "filters": [
                {
                    "package": "material_ranking",
                    "field": "metrics.show_cnt",
                    "operator": "top_percentile",
                    "value": 75,
                },
                {
                    "package": "material_ranking",
                    "field": "metrics.cvr",
                    "operator": "bottom_percentile",
                    "value": 25,
                },
            ],
            "fields": {},
            "order_by": [],
            "limit": 10,
            "joins": [{"package": "script", "on": "material_id"}],
        },
        "run_id": run_id,
    }


def test_phase_two_handoffs_are_current_model_only_and_do_not_collect():
    with tempfile.TemporaryDirectory() as directory:
        run_copy = Path(directory) / "run"
        shutil.copytree(REAL_RUN, run_copy)
        request = prepare_fact_selection_handoff(
            run_copy,
            "找出曝光高但转化差的素材",
        )

        assert request["request_type"] == "yuntu_fact_selection"
        assert request["host_context"]["response_schema"] == "FactSelectionSpec"
        assert get_workflow_status(run_copy)["status"] == "awaiting_fact_selection"
        assert not list(run_copy.glob("**/raw-csv/*"))[0].name == "never"


def test_apply_selection_then_prepare_analysis_uses_selected_local_facts():
    with tempfile.TemporaryDirectory() as directory:
        run_copy = Path(directory) / "run"
        shutil.copytree(REAL_RUN, run_copy)
        prepare_fact_selection_handoff(run_copy, "找出曝光高但转化差的素材")
        selection = _selection_result("e97b74711dbe4105bb7825038530aece")

        selected = apply_fact_selection_result(run_copy, selection)
        request = prepare_model_analysis_handoff(run_copy)

        assert selected["selection_summary"]["source_record_counts"]["material_ranking"] == 1000
        assert request["request_type"] == "yuntu_commercial_analysis"
        assert request["host_context"]["facts"]
        assert request["host_context"]["fact_refs"]
        assert get_workflow_status(run_copy)["status"] == "facts_selected"
        assert (run_copy / "analysis/fact-selection-spec.json").is_file()
        assert (run_copy / "analysis/selected-fact-context.json").is_file()


def test_apply_selection_validates_model_intent_against_original_question():
    with tempfile.TemporaryDirectory() as directory:
        run_copy = Path(directory) / "run"
        shutil.copytree(REAL_RUN, run_copy)
        prepare_fact_selection_handoff(run_copy, "找出曝光高但转化差的素材")
        payload = _selection_result("e97b74711dbe4105bb7825038530aece")
        payload["intent"]["business_question"] = "比较三个品牌"

        try:
            apply_fact_selection_result(run_copy, payload)
        except ValueError as exc:
            assert "business_question" in str(exc)
        else:
            raise AssertionError("mismatched intent should be rejected")


def test_workflow_cli_exposes_the_two_phase_local_fact_flow():
    with tempfile.TemporaryDirectory() as directory:
        run_copy = Path(directory) / "run"
        shutil.copytree(REAL_RUN, run_copy)
        output = run_copy / "analysis/workflow.md"
        selection_path = run_copy / "selection-result.json"
        selection_path.write_text(json.dumps(_selection_result("e97b74711dbe4105bb7825038530aece")), encoding="utf-8")

        first_status = collector.main([
            "workflow", "--run-dir", str(run_copy),
            "--business-question", "找出曝光高但转化差的素材",
            "--output", str(output),
        ])
        assert first_status == 0
        assert json.loads((run_copy / "analysis/fact-selection-request.json").read_text(encoding="utf-8"))["request_type"] == "yuntu_fact_selection"

        second_status = collector.main([
            "workflow", "--run-dir", str(run_copy),
            "--business-question", "找出曝光高但转化差的素材",
            "--fact-selection-result", str(selection_path),
            "--output", str(output),
        ])
        assert second_status == 0
        assert json.loads((run_copy / "analysis/model-analysis-request.json").read_text(encoding="utf-8"))["request_type"] == "yuntu_commercial_analysis"


def test_workflow_cli_replays_analysis_result_and_renders_selected_context():
    with tempfile.TemporaryDirectory() as directory:
        run_copy = Path(directory) / "run"
        shutil.copytree(REAL_RUN, run_copy)
        output = run_copy / "analysis/workflow.md"
        selection_path = run_copy / "selection-result.json"
        selection_path.write_text(json.dumps(_selection_result("e97b74711dbe4105bb7825038530aece")), encoding="utf-8")
        analysis_path = run_copy / "analysis-result.json"
        analysis_path.write_text(json.dumps({
            "results": [
                {
                    "section": "material_ranking",
                    "findings": [{
                        "claim": "高曝光素材中存在转化效率较低的样本",
                        "type": "inference",
                        "confidence": "medium",
                        "fact_refs": ["facts/material-ranking.json#/records/0"],
                    }],
                },
                {
                    "section": "script",
                    "findings": [],
                    "gaps": ["脚本字段为 source_empty，无法分析脚本钩子"],
                },
            ]
        }, ensure_ascii=False), encoding="utf-8")

        assert collector.main([
            "workflow", "--run-dir", str(run_copy),
            "--business-question", "找出曝光高但转化差的素材",
            "--output", str(output),
        ]) == 0
        assert collector.main([
            "workflow", "--run-dir", str(run_copy),
            "--business-question", "找出曝光高但转化差的素材",
            "--fact-selection-result", str(selection_path),
            "--output", str(output),
        ]) == 0
        selected_context = json.loads(
            (run_copy / "analysis/selected-fact-context.json").read_text(encoding="utf-8")
        )
        first_index = selected_context["sections"]["material_ranking"]["record_indices"][0]
        analysis_payload = json.loads(analysis_path.read_text(encoding="utf-8"))
        analysis_payload["results"][0]["findings"][0]["fact_refs"] = [
            f"facts/material-ranking.json#/records/{first_index}"
        ]
        analysis_path.write_text(json.dumps(analysis_payload, ensure_ascii=False), encoding="utf-8")
        assert collector.main([
            "workflow", "--run-dir", str(run_copy),
            "--business-question", "找出曝光高但转化差的素材",
            "--analysis-result", str(analysis_path),
            "--output", str(output),
        ]) == 0

        report = output.read_text(encoding="utf-8")
        assert "用户商业问题" in report
        assert "FactSelectionSpec" in report
        assert "1000" in report
        assert "source_empty" in report
        assert get_workflow_status(run_copy)["status"] == "analysis_completed"
