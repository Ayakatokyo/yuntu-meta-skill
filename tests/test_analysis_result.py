import unittest

from scripts.analysis_result import normalize_analysis_result, validate_analysis_result


FACT_INDEX = {
    "facts/material-ranking.json#/records/0": {
        "material_id": "101", "title": "#燕之屋", "selection_group": {"brand_name": ""},
        "list_context": {"brands": ["燕之屋"]},
    },
    "facts/audience.json#/records/0": {
        "material_id": "101", "raw_people_tags": ["新锐白领"],
    },
    "facts/script.json#/records/0": {
        "material_id": "101", "data_availability": {
            "script_text": {"available": False, "missing_reason": "source_empty"},
        },
    },
    "facts/highlight-frames.json#/records/0": {
        "material_id": "101", "frames": [{"second": 1}],
    },
}


class AnalysisResultTests(unittest.TestCase):
    def finding(self, ref="facts/material-ranking.json#/records/0", **changes):
        value = {
            "claim": "排名事实",
            "type": "fact",
            "confidence": "high",
            "fact_refs": [ref],
        }
        value.update(changes)
        return value

    def result(self, **changes):
        value = {
            "section": "material_ranking",
            "findings": [self.finding()],
            "gaps": [],
            "next_questions": [],
        }
        value.update(changes)
        return value

    def test_normalize_fills_optional_arrays_without_mutating_input(self):
        source = {"section": "audience", "findings": []}
        normalized = normalize_analysis_result(source)
        self.assertEqual(normalized["gaps"], [])
        self.assertEqual(normalized["next_questions"], [])
        self.assertNotIn("gaps", source)

    def test_missing_fact_refs_is_invalid(self):
        result = self.result(findings=[self.finding(fact_refs=[])])
        errors = validate_analysis_result(result, FACT_INDEX)
        self.assertTrue(any("fact_refs" in error for error in errors))

    def test_invalid_type_confidence_and_reference_are_reported(self):
        result = self.result(findings=[self.finding(
            type="observation", confidence="certain", fact_refs=["facts/nope#/records/0"]
        )])
        errors = validate_analysis_result(result, FACT_INDEX)
        self.assertTrue(any("type" in error for error in errors))
        self.assertTrue(any("confidence" in error for error in errors))
        self.assertTrue(any("does not resolve" in error for error in errors))

    def test_source_empty_can_only_be_reported_as_gap(self):
        invalid = self.result(
            section="script",
            findings=[self.finding("facts/script.json#/records/0", claim="脚本内容事实")],
        )
        self.assertTrue(any("source_empty" in error for error in validate_analysis_result(invalid, FACT_INDEX)))
        valid = self.result(section="script", findings=[], gaps=["script_text source_empty，不可分析"])
        self.assertEqual(validate_analysis_result(valid, FACT_INDEX), [])

    def test_highlight_fact_can_carry_script_availability_metadata(self):
        fact_index = dict(FACT_INDEX)
        fact_index["facts/highlight-frames.json#/records/0"] = {
            "material_id": "101", "frames": [{"second": 1}],
            "data_availability": {
                "script_text": {"available": False, "missing_reason": "source_empty"},
                "trends": {"available": True, "missing_reason": ""},
            },
        }
        result = self.result(
            section="highlight_frames",
            findings=[self.finding("facts/highlight-frames.json#/records/0", claim="高光帧记录显示第1秒存在指标高点")],
        )
        self.assertEqual(validate_analysis_result(result, fact_index), [])

    def test_brand_proxy_requires_inference_and_reduced_confidence(self):
        fact = self.result(findings=[self.finding(claim="标题识别品牌为燕之屋")])
        self.assertTrue(any("品牌" in error for error in validate_analysis_result(fact, FACT_INDEX)))
        allowed = self.result(findings=[self.finding(
            claim="标题识别品牌为燕之屋（推断）", type="inference", confidence="low"
        )])
        self.assertEqual(validate_analysis_result(allowed, FACT_INDEX), [])

    def test_causal_claim_is_rejected(self):
        causal = self.result(findings=[self.finding(claim="高光导致点击率提升")])
        self.assertTrue(any("因果" in error for error in validate_analysis_result(causal, FACT_INDEX)))

    def test_causal_claim_is_rejected_even_when_marked_for_validation(self):
        causal = self.result(findings=[self.finding(claim="高光导致点击率提升，待验证")])
        self.assertTrue(validate_analysis_result(causal, FACT_INDEX))

    def test_label_association_and_highlight_interpretation_require_inference(self):
        associated = self.result(findings=[self.finding(claim="标签共现与点击率相关")])
        self.assertTrue(any("inference" in error for error in validate_analysis_result(associated, FACT_INDEX)))
        highlighted = self.result(
            section="highlight_frames",
            findings=[self.finding("facts/highlight-frames.json#/records/0", claim="高光说明用户更喜欢这个画面")],
        )
        self.assertTrue(any("inference" in error for error in validate_analysis_result(highlighted, FACT_INDEX)))

    def test_script_source_empty_is_rejected_even_from_non_script_section(self):
        invalid = self.result(
            findings=[self.finding("facts/script.json#/records/0", claim="脚本事实")],
        )
        self.assertTrue(any("source_empty" in error for error in validate_analysis_result(invalid, FACT_INDEX)))


if __name__ == "__main__":
    unittest.main()
