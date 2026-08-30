import unittest

from scripts.analysis_spec import AnalysisSpec, parse_analysis_spec, validate_analysis_spec


def manifest():
    return {
        "schema_version": 1,
        "run_id": "run-1",
        "packages": {
            "material_ranking": {"path": "facts/material-ranking.json", "record_count": 10},
            "audience": {"path": "facts/audience.json", "record_count": 10},
            "script": {"path": "facts/script.json", "record_count": 2},
            "highlight_frames": {"path": "facts/highlight-frames.json", "record_count": 2},
        },
        "coverage": {"ranking_records": 10},
        "brand_classification": {
            "rule_version": "runtime-title-rule-v1",
            "candidate_brands": ["品牌A", "品牌B"],
            "counts": {"品牌A": 5, "品牌B": 3},
            "unknown_count": 2,
        },
    }


class AnalysisSpecTests(unittest.TestCase):
    def valid_payload(self):
        return {
            "analysis_id": "analysis-1",
            "run_id": "run-1",
            "sections": ["material_ranking", "audience"],
            "business_question": "比较素材表现并寻找可验证机会",
            "metric_focus": ["exposure", "click"],
            "filters": {"rank_range": [1, 10], "material_ids": []},
            "report_mode": "standard_with_custom_sections",
            "custom_sections": [],
        }

    def test_parse_returns_typed_spec_with_safe_defaults(self):
        spec = parse_analysis_spec(self.valid_payload())
        self.assertIsInstance(spec, AnalysisSpec)
        self.assertEqual(spec.sections, ("material_ranking", "audience"))
        self.assertEqual(spec.filters["rank_range"], (1, 10))

    def test_parse_preserves_brand_filter_as_a_typed_tuple(self):
        payload = self.valid_payload()
        payload["filters"]["brand_filter"] = ["品牌A", "未知品牌"]

        spec = parse_analysis_spec(payload)

        self.assertEqual(spec.filters["brand_filter"], ("品牌A", "未知品牌"))
        self.assertEqual(spec.to_dict()["filters"]["brand_filter"], ["品牌A", "未知品牌"])
        self.assertEqual(spec.brand_filter, ("品牌A", "未知品牌"))

    def test_parse_accepts_phase_two_top_level_filter_aliases(self):
        payload = self.valid_payload()
        payload.pop("filters")
        payload["brand_filter"] = ["品牌A"]
        payload["material_filter"] = {"rank_range": [2, 4], "material_ids": ["101"]}

        spec = parse_analysis_spec(payload)

        self.assertEqual(spec.filters["brand_filter"], ("品牌A",))
        self.assertEqual(spec.filters["rank_range"], (2, 4))
        self.assertEqual(spec.filters["material_ids"], ("101",))

    def test_validation_rejects_brand_outside_manifest_scope(self):
        payload = self.valid_payload()
        payload["filters"]["brand_filter"] = ["未指定品牌"]

        errors = validate_analysis_spec(parse_analysis_spec(payload), manifest())

        self.assertTrue(any("brand_filter" in error for error in errors))

    def test_rejects_unknown_module(self):
        payload = self.valid_payload()
        payload["sections"] = ["not_a_module"]
        with self.assertRaisesRegex(ValueError, "unsupported section"):
            parse_analysis_spec(payload)

    def test_rejects_empty_business_question(self):
        payload = self.valid_payload()
        payload["business_question"] = "  "
        with self.assertRaisesRegex(ValueError, "business_question"):
            parse_analysis_spec(payload)

    def test_rejects_out_of_bounds_rank_range(self):
        payload = self.valid_payload()
        payload["filters"]["rank_range"] = [0, 1001]
        with self.assertRaisesRegex(ValueError, "rank_range"):
            parse_analysis_spec(payload)

    def test_missing_run_id_is_reported_by_validation(self):
        payload = self.valid_payload()
        payload.pop("run_id")
        spec = parse_analysis_spec(payload)
        errors = validate_analysis_spec(spec, manifest())
        self.assertTrue(any("run_id" in error for error in errors))

    def test_validation_checks_run_and_package_availability(self):
        payload = self.valid_payload()
        payload["run_id"] = "other-run"
        current_manifest = manifest()
        current_manifest["packages"].pop("audience")
        errors = validate_analysis_spec(parse_analysis_spec(payload), current_manifest)
        self.assertTrue(any("run_id" in error for error in errors))
        self.assertTrue(any("audience" in error for error in errors))

    def test_rejects_malformed_custom_section(self):
        payload = self.valid_payload()
        payload["report_mode"] = "standard_with_custom_sections"
        payload["custom_sections"] = [1]
        with self.assertRaisesRegex(ValueError, "custom_sections"):
            parse_analysis_spec(payload)


if __name__ == "__main__":
    unittest.main()
