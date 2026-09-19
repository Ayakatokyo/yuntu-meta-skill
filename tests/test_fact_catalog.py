from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.fact_catalog import FactCatalog, build_fact_catalog
from scripts.fact_selection import (
    FactFilter,
    FactJoin,
    FactPackage,
    FactSelectionSpec,
    SelectionOperator,
)
from scripts.analysis_facts import execute_fact_selection


RUN_DIR = Path("runs/food-beverage-2026-0810-0820")


def test_build_fact_catalog_reads_manifest_metadata_for_real_run():
    catalog = build_fact_catalog(RUN_DIR)

    assert catalog.run_id == "e97b74711dbe4105bb7825038530aece"
    assert catalog.record_counts[FactPackage.MATERIAL_RANKING] == 1000
    assert catalog.record_counts[FactPackage.SCRIPT] == 4
    assert "metrics.ctr" in catalog.fields[FactPackage.MATERIAL_RANKING]
    assert catalog.available_fields[FactPackage.SCRIPT]["script_text"] == 0


def test_execute_fact_selection_finds_high_exposure_low_conversion_and_joins_details():
    spec = FactSelectionSpec(
        packages=(FactPackage.MATERIAL_RANKING, FactPackage.SCRIPT, FactPackage.HIGHLIGHT_FRAMES),
        filters=(
            FactFilter(
                FactPackage.MATERIAL_RANKING,
                "metrics.show_cnt",
                SelectionOperator.TOP_PERCENTILE,
                75,
            ),
            FactFilter(
                FactPackage.MATERIAL_RANKING,
                "metrics.cvr",
                SelectionOperator.BOTTOM_PERCENTILE,
                25,
            ),
        ),
        fields={FactPackage.MATERIAL_RANKING: ("material_id", "rank", "metrics", "material_tags")},
        order_by=(),
        limit=30,
        joins=(
            FactJoin(FactPackage.SCRIPT),
            FactJoin(FactPackage.HIGHLIGHT_FRAMES),
        ),
    )

    result = execute_fact_selection(RUN_DIR, spec)

    ranking = result.sections[FactPackage.MATERIAL_RANKING.value]["records"]
    selected_ids = {record["material_id"] for record in ranking}
    assert ranking
    assert len(ranking) <= 30
    assert all(record["metrics"]["show_cnt"] >= 24491.25 for record in ranking)
    assert all(record["metrics"]["cvr"] <= 0.01764726 for record in ranking)
    assert all(
        record["material_id"] in selected_ids
        for record in result.sections[FactPackage.SCRIPT.value]["records"]
    )
    assert result.selection_summary["source_record_counts"]["material_ranking"] == 1000


def test_execute_fact_selection_reports_empty_scripts_without_fabricating_them():
    spec = FactSelectionSpec(
        packages=(FactPackage.MATERIAL_RANKING, FactPackage.SCRIPT),
        filters=(
            FactFilter(
                FactPackage.MATERIAL_RANKING,
                "brand_classification.value",
                SelectionOperator.EQUALS,
                "小仙炖",
            ),
        ),
        fields={},
        order_by=(),
        limit=3,
        joins=(FactJoin(FactPackage.SCRIPT),),
    )

    result = execute_fact_selection(RUN_DIR, spec)

    assert any(gap["reason"] == "source_empty" for gap in result.data_gaps)
    assert all(record["script_text"] == "" for record in result.sections[FactPackage.SCRIPT.value]["records"])


def test_execute_fact_selection_rejects_unknown_field_before_reading_records():
    spec = FactSelectionSpec(
        packages=(FactPackage.MATERIAL_RANKING,),
        filters=(
            FactFilter(
                FactPackage.MATERIAL_RANKING,
                "metrics.not_a_real_metric",
                SelectionOperator.GTE,
                1,
            ),
        ),
        fields={},
        order_by=(),
        limit=None,
        joins=(),
    )

    with pytest.raises(ValueError, match="unknown fact field"):
        execute_fact_selection(RUN_DIR, spec)


def test_unknown_fact_field_error_lists_legal_fields_for_one_pass_repair():
    catalog = FactCatalog(
        run_id="run-1",
        schema_version=3,
        record_counts={FactPackage.MATERIAL_RANKING: 1},
        fields={FactPackage.MATERIAL_RANKING: ("metrics.ctr", "metrics.show_cnt")},
        available_fields={FactPackage.MATERIAL_RANKING: {"metrics.ctr": 1, "metrics.show_cnt": 1}},
        package_paths={FactPackage.MATERIAL_RANKING: "facts/material-ranking.json"},
    )
    spec = FactSelectionSpec(
        packages=(FactPackage.MATERIAL_RANKING,),
        filters=(FactFilter(
            FactPackage.MATERIAL_RANKING,
            "metrics.starShowCnt",
            SelectionOperator.GTE,
            1,
        ),),
        fields={}, order_by=(), limit=None, joins=(),
    )

    with patch("scripts.fact_catalog.build_fact_catalog", return_value=catalog):
        with pytest.raises(ValueError) as error:
            execute_fact_selection(Path("/not-read"), spec)

    message = str(error.value)
    assert "合法字段" in message
    assert "metrics.ctr" in message
    assert "metrics.show_cnt" in message
