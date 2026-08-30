import unittest

from scripts.analysis_report import render_analysis_report
from scripts.analysis_facts import build_fact_index
from scripts.analysis_spec import parse_analysis_spec


class AnalysisReportTests(unittest.TestCase):
    def setUp(self):
        self.spec = parse_analysis_spec({
            "analysis_id": "analysis-1", "run_id": "run-1",
            "sections": ["material_ranking", "audience"],
            "business_question": "比较素材表现", "filters": {"rank_range": [1, 1]},
        })
        self.fact_index = {
            "facts/material-ranking.json#/records/0": {
                "material_id": "101", "rank": 1,
                "brand_classification": {
                    "value": "品牌A", "matchedBrands": ["品牌A"],
                    "source": "runtime_title_rule", "match_tokens": {"品牌A": ["品牌A"]},
                },
            },
            "facts/audience.json#/records/0": {"material_id": "101", "raw_people_tags": ["女"]},
        }
        self.results = [
            {"section": "material_ranking", "findings": [{
                "claim": "榜单记录显示素材位于第1名。", "type": "fact", "confidence": "high",
                "fact_refs": ["facts/material-ranking.json#/records/0"],
            }], "gaps": [], "next_questions": []},
            {"section": "audience", "findings": [{
                "claim": "人群记录包含女性标签。", "type": "fact", "confidence": "high",
                "fact_refs": ["facts/audience.json#/records/0"],
            }], "gaps": [], "next_questions": []},
        ]
        self.metadata = {
            "run_id": "run-1", "analysis_time": "2026-08-30T10:00:00Z",
            "facts_version": 1, "prompt_version": "yuntu-commercial-analysis-v1",
            "fact_index": self.fact_index,
            "coverage": {"ranking_records": 1, "audience_records": 1},
            "package_paths": [
                "facts/material-ranking.json", "facts/audience.json",
                "facts/script.json", "facts/highlight-frames.json",
            ],
            "brand_classification": {
                "rule_version": "runtime-title-rule-v1",
                "candidate_brands": ["品牌A", "品牌B"],
                "counts": {"品牌A": 1, "品牌B": 0}, "unknown_count": 0,
            },
            "brand_audit_records": [self.fact_index["facts/material-ranking.json#/records/0"]],
        }

    def test_single_or_multi_module_report_has_fixed_skeleton_and_metadata(self):
        report = render_analysis_report(self.spec, self.results, self.metadata)
        for heading in (
            "执行摘要", "分析范围、样本和方法", "素材榜单表现", "人群结构",
            "脚本可用性与数据缺口", "高光帧与内容节奏", "跨模块观察",
            "商业机会与待验证假设", "执行动作建议", "数据限制与下一轮采集建议",
            "事实引用附录",
        ):
            self.assertIn(f"## {heading}", report)
        self.assertIn("run-1", report)
        self.assertIn("2026-08-30T10:00:00Z", report)
        self.assertIn("facts/material-ranking.json#/records/0", report)
        self.assertIn("facts/script.json", report)
        self.assertIn("相关不等于因果", report)
        self.assertIn("品牌代理识别", report)

    def test_report_displays_brand_scope_and_match_token_audit(self):
        report = render_analysis_report(self.spec, self.results, self.metadata)

        self.assertIn("品牌候选范围：品牌A、品牌B", report)
        self.assertIn("runtime-title-rule-v1", report)
        self.assertIn("未知品牌数量：0", report)
        self.assertIn("matchedBrands", report)
        self.assertIn("match_tokens", report)

    def test_custom_sections_keep_declared_order(self):
        spec = parse_analysis_spec({
            "analysis_id": "analysis-2", "run_id": "run-1", "sections": ["audience"],
            "business_question": "观察人群", "filters": {"rank_range": [1, 1]},
            "report_mode": "standard_with_custom_sections",
            "custom_sections": ["风险", "机会"],
        })
        custom_results = [self.results[1]] + [
            {"section": "风险", "findings": [{
                "claim": "需要补充验证。", "type": "recommendation", "confidence": "low",
                "fact_refs": ["facts/audience.json#/records/0"],
            }], "gaps": [], "next_questions": []},
            {"section": "机会", "findings": [{
                "claim": "可以设计下一轮实验。", "type": "recommendation", "confidence": "low",
                "fact_refs": ["facts/audience.json#/records/0"],
            }], "gaps": [], "next_questions": []},
        ]
        report = render_analysis_report(spec, custom_results, self.metadata)
        self.assertLess(report.index("## 风险"), report.index("## 机会"))

    def test_invalid_result_is_rejected_before_rendering(self):
        invalid = [dict(self.results[0], findings=[{
            "claim": "没有引用的结论", "type": "fact", "confidence": "high", "fact_refs": [],
        }])]
        with self.assertRaisesRegex(ValueError, "校验失败"):
            render_analysis_report(self.spec, invalid, self.metadata)

    def test_unselected_result_section_is_rejected(self):
        invalid = self.results + [{
            "section": "script", "findings": [], "gaps": ["不可分析"], "next_questions": [],
        }]
        with self.assertRaisesRegex(ValueError, "未选择"):
            render_analysis_report(self.spec, invalid, self.metadata)

    def test_missing_selected_section_result_is_rejected(self):
        invalid = [self.results[0]]
        with self.assertRaisesRegex(ValueError, "缺少"):
            render_analysis_report(self.spec, invalid, self.metadata)


if __name__ == "__main__":
    unittest.main()
