import unittest

from scripts.analysis_facts import build_fact_index
from scripts.analysis_prompt import build_prompt_packet
from scripts.analysis_spec import parse_analysis_spec
from scripts.model_analysis_request import (
    build_model_analysis_request,
    validate_model_analysis_request,
)


class ModelAnalysisRequestTests(unittest.TestCase):
    def setUp(self):
        self.spec = parse_analysis_spec({
            "analysis_id": "analysis-1",
            "run_id": "run-1",
            "sections": ["material_ranking", "audience"],
            "business_question": "比较素材表现和人群差异",
            "filters": {"rank_range": [1, 1]},
        })
        self.selected_facts = {
            "manifest": {
                "schema_version": 3,
                "run_id": "run-1",
                "brand_classification": {"candidate_brands": ["品牌A"]},
            },
            "sections": {
                "material_ranking": {
                    "path": "facts/material-ranking.json",
                    "records": [{"material_id": "101", "rank": 1}],
                    "record_indices": [0],
                },
                "audience": {
                    "path": "facts/audience.json",
                    "records": [{"material_id": "101", "raw_people_tags": ["女"]}],
                    "record_indices": [0],
                },
                "script": {
                    "path": "facts/script.json",
                    "records": [{"material_id": "101"}],
                    "record_indices": [0],
                },
            },
        }

    def test_request_contains_analysis_spec_selected_facts_index_and_schema(self):
        index = build_fact_index(self.selected_facts)
        packet = build_prompt_packet(self.spec, self.selected_facts, index)
        request = build_model_analysis_request(self.spec, self.selected_facts, index)

        self.assertEqual(request["request_type"], "yuntu_commercial_analysis")
        self.assertEqual(request["request_version"], 2)
        self.assertEqual(request["host_context"]["analysis_id"], "analysis-1")
        self.assertEqual(request["host_context"]["run_id"], "run-1")
        self.assertEqual(request["host_context"]["analysis_spec"], self.spec.to_dict())
        self.assertEqual(request["host_context"]["facts"], packet["facts"])
        self.assertEqual(
            set(request["host_context"]["fact_refs"]),
            {"facts/material-ranking.json#/records/0", "facts/audience.json#/records/0"},
        )
        self.assertEqual(request["host_context"]["response_schema"], "AnalysisResult")
        self.assertNotIn("fact_index", request["host_context"])
        self.assertIn("facts_version", request["local_audit"])
        self.assertIn("fact_package_hashes", request["local_audit"])
        self.assertEqual(validate_model_analysis_request(request), [])

    def test_request_excludes_unselected_fact_packages(self):
        spec = parse_analysis_spec({
            "analysis_id": "analysis-2",
            "run_id": "run-1",
            "sections": ["audience"],
            "business_question": "观察人群",
            "filters": {"rank_range": [1, 1]},
        })
        index = build_fact_index(self.selected_facts)
        request = build_model_analysis_request(spec, self.selected_facts, index)

        self.assertEqual(set(request["host_context"]["facts"]), {"facts/audience.json"})
        self.assertTrue(all("script.json" not in ref for ref in request["host_context"]["fact_refs"]))

    def test_request_includes_script_brand_and_non_causal_quality_rules(self):
        spec = parse_analysis_spec({
            "analysis_id": "analysis-3",
            "run_id": "run-1",
            "sections": ["script", "material_ranking"],
            "business_question": "比较品牌并检查脚本",
            "filters": {"rank_range": [1, 1]},
        })
        index = build_fact_index(self.selected_facts)
        request = build_model_analysis_request(spec, self.selected_facts, index)
        rules = " ".join(request["host_context"]["system_rules"])

        self.assertIn("source_empty", rules)
        self.assertIn("品牌代理", rules)
        self.assertIn("相关不等于因果", rules)
        self.assertEqual(request["host_context"]["analysis_spec"]["business_question"], "比较品牌并检查脚本")

    def test_invalid_request_reports_contract_errors(self):
        errors = validate_model_analysis_request({
            "request_type": "wrong",
            "request_version": 1,
            "host_context": {"response_schema": "Other"},
        })

        self.assertTrue(any("request_type" in error for error in errors))
        self.assertTrue(any("request_version" in error for error in errors))
        self.assertTrue(any("response_schema" in error for error in errors))
        self.assertTrue(any("analysis_spec" in error for error in errors))

    def test_request_rejects_fact_index_entries_outside_selected_facts(self):
        request = build_model_analysis_request(
            self.spec,
            self.selected_facts,
            build_fact_index(self.selected_facts),
        )
        request["host_context"]["fact_refs"].append("facts/script.json#/records/0")

        errors = validate_model_analysis_request(request)

        self.assertTrue(any("fact_refs" in error and "facts" in error for error in errors))

    def test_request_does_not_duplicate_fact_records_for_local_audit(self):
        index = build_fact_index(self.selected_facts)
        request = build_model_analysis_request(self.spec, self.selected_facts, index)

        self.assertNotIn("fact_index", request)
        self.assertNotIn("fact_index", request["host_context"])
        self.assertNotIn("fact-summary.json", str(request))
        self.assertEqual(
            set(request["local_audit"]),
            {
                "analysis_id", "run_id", "facts_version", "prompt_version",
                "fact_package_hashes", "source_artifact_hashes", "selected_fact_paths",
            },
        )


if __name__ == "__main__":
    unittest.main()
