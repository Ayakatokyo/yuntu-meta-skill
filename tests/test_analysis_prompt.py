import unittest

from scripts.analysis_facts import build_fact_index
from scripts.analysis_prompt import build_fact_selection_prompt, build_prompt_packet
from scripts.fact_catalog import FactCatalog
from scripts.fact_selection import FactPackage
from scripts.analysis_spec import parse_analysis_spec


class AnalysisPromptTests(unittest.TestCase):
    def setUp(self):
        self.spec = parse_analysis_spec({
            "analysis_id": "analysis-1", "run_id": "run-1",
            "sections": ["material_ranking", "audience", "script"],
            "business_question": "比较素材表现并寻找可验证的创意机会",
            "metric_focus": ["exposure", "click"],
            "filters": {"rank_range": [1, 2]},
        })
        self.facts = {
            "manifest": {"schema_version": 1, "run_id": "run-1"},
            "sections": {
                "material_ranking": {
                    "path": "facts/material-ranking.json", "record_count": 1,
                    "records": [{"material_id": "101", "rank": 1}],
                },
                "audience": {
                    "path": "facts/audience.json", "record_count": 1,
                    "records": [{"material_id": "101", "raw_people_tags": ["女"]}],
                },
                "script": {
                    "path": "facts/script.json", "record_count": 1,
                    "records": [{"material_id": "101", "data_availability": {
                        "script_text": {"available": False, "missing_reason": "source_empty"}
                    }}],
                },
            },
        }

    def test_packet_contains_question_boundaries_facts_and_reference_rules(self):
        packet = build_prompt_packet(self.spec, self.facts, build_fact_index(self.facts))
        self.assertEqual(packet["business_question"], self.spec.business_question)
        self.assertEqual(set(packet["sections"]), set(self.spec.sections))
        self.assertIn("facts/material-ranking.json", packet["facts"])
        self.assertIn("fact_refs", packet["rules"]["required_fields"])
        self.assertIn("相关不等于因果", " ".join(packet["rules"]["quality_gates"]))

    def test_source_empty_script_adds_non_analyzable_constraint(self):
        packet = build_prompt_packet(self.spec, self.facts, build_fact_index(self.facts))
        self.assertTrue(any("source_empty" in rule for rule in packet["rules"]["quality_gates"]))
        self.assertIn("不可分析", packet["module_requirements"]["script"])

    def test_unselected_fact_package_is_not_in_prompt(self):
        spec = parse_analysis_spec({
            "analysis_id": "analysis-2", "run_id": "run-1", "sections": ["audience"],
            "business_question": "观察人群", "filters": {"rank_range": [1, 1]},
        })
        packet = build_prompt_packet(spec, self.facts, build_fact_index(self.facts))
        self.assertEqual(set(packet["facts"]), {"facts/audience.json"})

    def test_module_requirements_cover_cross_module_analysis_boundaries(self):
        spec = parse_analysis_spec({
            "analysis_id": "analysis-3", "run_id": "run-1",
            "sections": ["material_ranking", "audience", "highlight_frames"],
            "business_question": "寻找机会", "filters": {"rank_range": [1, 1]},
        })
        packet = build_prompt_packet(spec, self.facts, build_fact_index(self.facts))
        requirements = " ".join(packet["module_requirements"].values())
        self.assertIn("TOP 分层", requirements)
        self.assertIn("交叉", requirements)
        self.assertIn("高光时间", requirements)
        self.assertIn("selection_group", " ".join(packet["rules"]["quality_gates"]))

    def test_packet_exposes_runtime_brand_scope_and_filter_boundary(self):
        spec = parse_analysis_spec({
            "analysis_id": "analysis-brand", "run_id": "run-1",
            "sections": ["material_ranking"], "business_question": "按品牌比较",
            "filters": {"rank_range": [1, 1], "brand_filter": ["品牌A"]},
        })
        facts = dict(self.facts)
        facts["manifest"] = {
            "schema_version": 3, "run_id": "run-1",
            "brand_classification": {
                "rule_version": "runtime-title-rule-v1",
                "candidate_brands": ["品牌A", "品牌B"],
                "counts": {"品牌A": 1, "品牌B": 0}, "unknown_count": 0,
            },
        }

        packet = build_prompt_packet(spec, facts, build_fact_index(facts))

        self.assertEqual(packet["brand_classification"]["candidate_brands"], ["品牌A", "品牌B"])
        rules = " ".join(packet["rules"]["quality_gates"])
        self.assertIn("manifest", rules)
        self.assertIn("brand_filter", rules)

    def test_fact_selection_prompt_contains_intent_rules_and_catalog_only(self):
        catalog = FactCatalog(
            run_id="run-1",
            schema_version=3,
            record_counts={FactPackage.MATERIAL_RANKING: 1},
            fields={FactPackage.MATERIAL_RANKING: ("metrics.ctr",)},
            available_fields={FactPackage.MATERIAL_RANKING: {"metrics.ctr": 1}},
            package_paths={FactPackage.MATERIAL_RANKING: "facts/material-ranking.json"},
        )
        prompt = build_fact_selection_prompt(self.spec, catalog)

        self.assertEqual(prompt["business_question"], self.spec.business_question)
        self.assertIn("fact_catalog", prompt)
        self.assertNotIn("records", prompt["fact_catalog"])
        self.assertIn("不得生成 QuerySpec", " ".join(prompt["rules"]))
        labels = prompt["fact_catalog"]["packages"]["material_ranking"]["business_field_labels"]
        self.assertEqual(labels["metrics.ctr"], "CTR（点击率）")
        self.assertIn("业务字段", " ".join(prompt["rules"]))

    def test_analysis_packet_exposes_business_labels_without_tightening_result_schema(self):
        packet = build_prompt_packet(self.spec, self.facts, build_fact_index(self.facts))

        self.assertEqual(packet["business_field_labels"]["metrics.show_cnt"], "曝光量")
        self.assertEqual(packet["business_field_labels"]["script_text"], "视频脚本")
        self.assertIn("业务字段", packet["rules"]["report_language"])
        self.assertEqual(packet["rules"]["required_fields"], ["claim", "type", "confidence", "fact_refs"])


if __name__ == "__main__":
    unittest.main()
