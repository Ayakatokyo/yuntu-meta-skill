import pytest

from scripts.analysis_intent import (
    AnalysisIntent,
    AnalysisObjective,
    FactPackage,
    parse_analysis_intent,
)


def test_analysis_intent_round_trips_with_closed_enums():
    intent = AnalysisIntent(
        business_question="找出曝光高但转化差的素材",
        objectives=(AnalysisObjective.FIND_HIGH_EXPOSURE_LOW_CONVERSION,),
        metrics=("show_cnt", "cvr"),
        dimensions=("brand",),
        required_packages=(FactPackage.MATERIAL_RANKING,),
        material_scope=None,
        creative_analysis_required=False,
    )

    payload = intent.to_dict()
    restored = parse_analysis_intent(payload)

    assert restored == intent
    assert payload["objectives"] == ["find_high_exposure_low_conversion"]
    assert payload["required_packages"] == ["material_ranking"]


def test_analysis_intent_rejects_blank_question_and_duplicate_metrics():
    with pytest.raises(ValueError, match="business_question"):
        AnalysisIntent(
            business_question=" ",
            objectives=(),
            metrics=(),
            dimensions=(),
            required_packages=(),
            material_scope=None,
            creative_analysis_required=False,
        )

    with pytest.raises(ValueError, match="metrics must not contain duplicates"):
        AnalysisIntent(
            business_question="比较素材",
            objectives=(),
            metrics=("ctr", "ctr"),
            dimensions=(),
            required_packages=(),
            material_scope=None,
            creative_analysis_required=False,
        )


def test_parse_analysis_intent_rejects_unknown_package_and_objective():
    with pytest.raises(ValueError, match="unsupported objective"):
        parse_analysis_intent({
            "business_question": "比较素材",
            "objectives": ["invented_objective"],
            "metrics": [],
            "dimensions": [],
            "required_packages": [],
            "creative_analysis_required": False,
        })

    with pytest.raises(ValueError, match="unsupported fact package"):
        parse_analysis_intent({
            "business_question": "比较素材",
            "objectives": [],
            "metrics": [],
            "dimensions": [],
            "required_packages": ["arbitrary_file"],
            "creative_analysis_required": False,
        })
