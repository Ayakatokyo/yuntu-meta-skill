from pathlib import Path

from scripts.analysis_spec import parse_analysis_spec
from scripts.fact_catalog import build_fact_catalog
from scripts.model_analysis_request import (
    FACT_SELECTION_REQUEST_TYPE,
    build_fact_selection_request,
    validate_fact_selection_request,
)


RUN_DIR = Path("runs/food-beverage-2026-0810-0820")


def test_selection_request_exposes_catalog_but_not_raw_facts():
    spec = parse_analysis_spec({
        "analysis_id": "analysis-select-1",
        "run_id": "e97b74711dbe4105bb7825038530aece",
        "sections": ["material_ranking", "script", "highlight_frames"],
        "business_question": "找出曝光高但转化差的素材",
    })
    catalog = build_fact_catalog(RUN_DIR)

    request = build_fact_selection_request(spec, catalog)

    assert request["request_type"] == FACT_SELECTION_REQUEST_TYPE
    assert request["host_context"]["response_schema"] == "FactSelectionSpec"
    assert request["host_context"]["fact_catalog"]["packages"]["material_ranking"]["record_count"] == 1000
    assert "records" not in request["host_context"]["fact_catalog"]["packages"]["material_ranking"]


def test_selection_request_validation_rejects_collector_fields_and_invalid_response_schema():
    request = {
        "request_type": FACT_SELECTION_REQUEST_TYPE,
        "request_version": 1,
        "host_context": {
            "analysis_id": "analysis-select-1",
            "run_id": "run-1",
            "analysis_spec": {},
            "fact_catalog": {"packages": {}},
            "response_schema": "WrongSchema",
        },
        "local_audit": {"analysis_id": "analysis-select-1", "run_id": "run-1"},
        "collector_params": {"custom_start_date": "2026-01-01"},
    }

    errors = validate_fact_selection_request(request)

    assert any("response_schema" in error for error in errors)
    assert any("collector" in error for error in errors)
