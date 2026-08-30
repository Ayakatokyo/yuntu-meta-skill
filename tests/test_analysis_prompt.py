import unittest

from scripts.analysis_facts import build_fact_index
from scripts.analysis_prompt import build_prompt_packet
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


if __name__ == "__main__":
    unittest.main()
