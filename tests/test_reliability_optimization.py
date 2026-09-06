import hashlib
import json
from pathlib import Path

import pytest

from scripts.analysis_intent import parse_analysis_intent
from scripts.analysis_report import render_analysis_report
from scripts.analysis_result import validate_analysis_result
from scripts.analysis_spec import parse_analysis_spec
from scripts.fact_catalog import build_fact_catalog
from scripts.fact_reference import FactReferenceError, parse_fact_ref
from scripts.fact_selection import FactAggregation, FactPackage, FactSelectionSpec
from scripts.analysis_facts import execute_fact_selection
from scripts.model_analysis_request import (
    build_fact_selection_request,
    build_model_analysis_request,
)
from scripts.workflow_state import (
    WorkflowStateError,
    begin_model_analysis,
    complete_model_analysis,
    fail_model_analysis,
    get_workflow_status,
    set_stage,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _synthetic_run(root: Path, size: int = 120) -> None:
    records = [
        {
            "material_id": str(index),
            "rank": index + 1,
            "metrics": {"show_cnt": index + 1, "ctr": index / 100},
            "data_availability": {"metrics": {"available": True, "missing_reason": ""}},
        }
        for index in range(size)
    ]
    packages = {}
    for package_name, package_file, package_records in (
        ("material_ranking", "material-ranking.json", records),
        ("audience", "audience.json", records[:2]),
        ("script", "script.json", [{"material_id": "0", "script_text": {"available": False, "missing_reason": "source_empty"}}]),
        ("highlight_frames", "highlight-frames.json", records[:2]),
    ):
        package_path = root / "facts" / package_file
        payload = {"schema_version": 4, "records": package_records}
        _write_json(package_path, payload)
        packages[package_name] = {
            "path": f"facts/{package_file}",
            "record_count": len(package_records),
            "sha256": hashlib.sha256(package_path.read_bytes()).hexdigest(),
        }
    _write_json(
        root / "facts" / "manifest.json",
        {"schema_version": 4, "run_id": "run-1", "packages": packages},
    )
    _write_json(root / "run-summary.json", {"runId": "run-1", "status": "ready_for_analysis"})


def test_fact_ref_rejects_legacy_alias_with_structured_canonical_suggestion():
    assert parse_fact_ref("facts/material-ranking.json#/records/7").source_index == 7

    with pytest.raises(FactReferenceError) as caught:
        parse_fact_ref("facts/material_ranking.json#/records/7")

    assert caught.value.code == "fact_ref_legacy_alias"
    assert caught.value.suggestion == "facts/material-ranking.json#/records/7"


def test_analysis_intent_preserves_the_customer_question_and_unsupported_meaning():
    intent = parse_analysis_intent(
        {
            "business_question": "我想比较不同人群的内容表现，并说明哪些因素值得继续验证",
            "original_question": "我想比较不同人群的内容表现，并说明哪些因素值得继续验证",
            "research_object": "内容表现与人群差异",
            "operation": "比较并提出验证方向",
            "metrics": ["ctr"],
            "dimensions": ["audience"],
            "scope": {"rank_range": [1, 20]},
            "expected_output": "对比表和待验证问题",
            "unsupported_requests": [
                {"request": "ROI", "reason": "事实包没有 ROI 字段"},
            ],
            "objectives": [],
            "required_packages": ["material_ranking", "audience"],
            "creative_analysis_required": False,
        }
    )

    assert intent.original_question.startswith("我想比较")
    assert intent.scope == {"rank_range": [1, 20]}
    assert intent.unsupported_requests[0]["request"] == "ROI"
    assert intent.to_dict()["unsupported_requests"][0]["reason"] == "事实包没有 ROI 字段"


def test_selection_uses_local_aggregates_and_caps_model_records_per_package(tmp_path):
    _synthetic_run(tmp_path)
    catalog = build_fact_catalog(tmp_path)
    assert "mean" in catalog.capabilities[FactPackage.MATERIAL_RANKING]["metrics.ctr"]["aggregations"]

    selection = FactSelectionSpec(
        packages=(FactPackage.MATERIAL_RANKING,),
        filters=(),
        fields={FactPackage.MATERIAL_RANKING: ("material_id", "metrics.ctr")},
        order_by=(),
        limit=None,
        joins=(),
        aggregations=(
            FactAggregation(FactPackage.MATERIAL_RANKING, "metrics.ctr", "mean"),
            FactAggregation(FactPackage.MATERIAL_RANKING, "metrics.ctr", "percentile", 90),
        ),
    )

    result = execute_fact_selection(tmp_path, selection)
    section = result.sections[FactPackage.MATERIAL_RANKING.value]
    assert section["source_record_count"] == 120
    assert section["record_count"] == 100
    assert len(section["record_indices"]) == 100
    assert result.selection_summary["truncation"]["material_ranking"]["reason"]
    assert result.aggregates["material_ranking"]["metrics.ctr"]["mean"] == pytest.approx(0.595)
    assert result.aggregates["material_ranking"]["metrics.ctr"]["percentile_90"] == pytest.approx(1.071)


def test_handoffs_expose_catalog_then_only_selected_context(tmp_path):
    _synthetic_run(tmp_path, size=2)
    spec = parse_analysis_spec(
        {
            "analysis_id": "analysis-1",
            "run_id": "run-1",
            "sections": ["material_ranking"],
            "business_question": "比较内容表现",
            "filters": {"rank_range": [1, 2]},
        }
    )
    catalog = build_fact_catalog(tmp_path)
    first = build_fact_selection_request(spec, catalog)
    assert "facts" not in first["host_context"]
    assert "fact_catalog" in first["host_context"]

    selected = {
        "manifest": json.loads((tmp_path / "facts/manifest.json").read_text()),
        "sections": {
            "material_ranking": {
                "path": "facts/material-ranking.json",
                "records": [{"material_id": "0", "metrics": {"ctr": 0.1}}],
                "record_indices": [0],
            }
        },
        "aggregates": {"material_ranking": {"metrics.ctr": {"mean": 0.1}}},
        "data_gaps": [],
    }
    request = build_model_analysis_request(spec, selected, {
        "facts/material-ranking.json#/records/0": selected["sections"]["material_ranking"]["records"][0]
    })
    context = request["host_context"]
    assert context["original_question"] == "比较内容表现"
    assert context["allowed_fact_refs"] == ["facts/material-ranking.json#/records/0"]
    assert context["local_aggregates"] == selected["aggregates"]
    assert context["selected_records"]["facts/material-ranking.json"][0]["material_id"] == "0"


def test_failed_analysis_is_audited_and_retryable_without_recollection(tmp_path):
    set_stage(tmp_path, "ready_for_analysis")
    begin_model_analysis(tmp_path, "analysis-1")
    fail_model_analysis(tmp_path, "analysis-1", "invalid fact reference")

    failed = get_workflow_status(tmp_path)
    assert failed["status"] == "analysis_failed"
    attempts = json.loads((tmp_path / "analysis" / "analysis-attempts.json").read_text())
    assert attempts[-1]["status"] == "failed"

    begin_model_analysis(tmp_path, "analysis-1-retry")
    result_path = tmp_path / "analysis" / "result.json"
    _write_json(result_path, {"results": []})
    complete_model_analysis(tmp_path, result_path)
    assert get_workflow_status(tmp_path)["status"] == "analysis_completed"
    attempts = json.loads((tmp_path / "analysis" / "analysis-attempts.json").read_text())
    assert [attempt["status"] for attempt in attempts[-2:]] == ["failed", "completed"]


def test_analysis_cannot_complete_when_report_artifact_is_missing(tmp_path):
    set_stage(tmp_path, "ready_for_analysis")
    begin_model_analysis(tmp_path, "analysis-1")
    result_path = tmp_path / "analysis" / "result.json"
    _write_json(result_path, {"results": []})

    with pytest.raises(WorkflowStateError, match="report is missing"):
        complete_model_analysis(tmp_path, result_path, tmp_path / "analysis" / "report.md")


def test_result_validation_reports_canonical_fact_ref_errors():
    errors = validate_analysis_result(
        {
            "section": "material_ranking",
            "findings": [{
                "claim": "事实",
                "type": "fact",
                "confidence": "high",
                "fact_refs": ["facts/material_ranking.json#/records/0"],
            }],
        },
        {"facts/material-ranking.json#/records/0": {"material_id": "0"}},
    )
    assert any(error["code"] == "fact_ref_legacy_alias" for error in errors)


def test_report_transparency_contains_intent_selection_and_gap_without_business_interpretation():
    spec = parse_analysis_spec(
        {
            "analysis_id": "analysis-1",
            "run_id": "run-1",
            "sections": ["material_ranking"],
            "business_question": "比较内容表现",
        }
    )
    report = render_analysis_report(
        spec,
        [{"section": "material_ranking", "findings": [], "gaps": [], "next_questions": []}],
        {
            "run_id": "run-1",
            "analysis_time": "2026-09-06T00:00:00Z",
            "facts_version": 4,
            "prompt_version": "test",
            "fact_index": {},
            "coverage": {},
            "package_paths": [],
            "phase_two": {
                "business_question": "比较内容表现",
                "intent": {
                    "original_question": "比较内容表现",
                    "research_object": "内容",
                    "operation": "比较",
                    "metrics": ["ctr"],
                    "dimensions": ["audience"],
                    "scope": {"rank_range": [1, 20]},
                    "expected_output": "对比",
                    "unsupported_requests": [{"request": "ROI", "reason": "缺字段"}],
                },
                "selection_spec": {"packages": ["material_ranking"], "limit": None},
                "selection_summary": {"truncation": {"material_ranking": {"reason": "默认上限 100"}}},
                "data_gaps": ["ROI：缺字段"],
            },
        },
    )
    assert "客户原问题" in report
    assert "unsupported_requests" in report
    assert "默认上限 100" in report
    assert "ROI：缺字段" in report
