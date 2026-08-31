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
            "一、核心结论", "二、行动建议", "三、素材榜单分析", "四、人群分析",
            "五、脚本分析", "六、高光帧分析",
            "八、数据限制与下一步", "附录 A：证据索引", "附录 B：结论审计",
        ):
            self.assertIn(f"## {heading}", report)
        self.assertIn("run-1", report)
        self.assertIn("2026-08-30T10:00:00Z", report)
        self.assertIn("facts/material-ranking.json#/records/0", report)
        self.assertIn("facts/script.json", report)
        self.assertIn("完整 fact_refs 索引", report)
        self.assertIn("相关线索不等于因果关系", report)
        self.assertIn("品牌代理识别", report)

    def test_body_uses_short_evidence_refs_and_moves_audit_metadata_to_appendices(self):
        report = render_analysis_report(self.spec, self.results, self.metadata)
        body = report.split("## 附录 A：证据索引", 1)[0]
        appendix = report.split("## 附录 A：证据索引", 1)[1]

        self.assertIn("[E1]", body)
        self.assertNotIn("[fact/high]", body)
        self.assertNotIn("[inference/medium]", body)
        self.assertNotIn("fact_refs:", body)
        self.assertIn("[E1]", appendix)
        self.assertIn("facts/material-ranking.json#/records/0", appendix)
        self.assertIn("类型：fact", appendix)
        self.assertIn("置信度：high", appendix)

    def test_repeated_fact_ref_reuses_one_evidence_id(self):
        repeated = [
            self.results[0],
            {"section": "audience", "findings": [{
                "claim": "同一事实记录可支撑另一条核验说明。", "type": "inference", "confidence": "medium",
                "fact_refs": ["facts/material-ranking.json#/records/0"],
            }]},
        ]
        report = render_analysis_report(self.spec, repeated, self.metadata)
        appendix = report.split("## 附录 A：证据索引", 1)[1]

        self.assertIn("同一事实记录可支撑另一条核验说明。 [E1]", report)
        self.assertEqual(appendix.count("[E1] `facts/material-ranking.json#/records/0`"), 1)
        self.assertNotIn("[E2] `facts/material-ranking.json#/records/0`", appendix)

    def test_fact_package_chapters_are_fixed_order_and_unselected_module_is_explicit(self):
        spec = parse_analysis_spec({
            "analysis_id": "analysis-all", "run_id": "run-1",
            "sections": ["material_ranking", "audience", "script", "highlight_frames"],
            "business_question": "比较四类事实包", "filters": {"rank_range": [1, 1]},
        })
        fact_index = dict(self.fact_index)
        fact_index.update({
            "facts/script.json#/records/0": {"material_id": "101"},
            "facts/highlight-frames.json#/records/0": {"material_id": "101"},
        })
        metadata = dict(self.metadata, fact_index=fact_index)
        report = render_analysis_report(spec, [
            {"section": "highlight_frames", "findings": [{
                "claim": "高光帧记录可按秒点核验。", "type": "fact", "confidence": "high",
                "fact_refs": ["facts/highlight-frames.json#/records/0"],
            }]},
            {"section": "material_ranking", "findings": [{
                "claim": "榜单记录排名为第1名。", "type": "fact", "confidence": "high",
                "fact_refs": ["facts/material-ranking.json#/records/0"],
            }]},
            {"section": "script", "findings": [{
                "claim": "脚本记录可供复核。", "type": "fact", "confidence": "high",
                "fact_refs": ["facts/script.json#/records/0"],
            }]},
            {"section": "audience", "findings": [{
                "claim": "人群记录包含女性标签。", "type": "fact", "confidence": "high",
                "fact_refs": ["facts/audience.json#/records/0"],
            }]},
        ], metadata)

        positions = [report.index(f"## {heading}") for heading in (
            "三、素材榜单分析", "四、人群分析", "五、脚本分析", "六、高光帧分析",
        )]
        self.assertEqual(positions, sorted(positions))

        unselected_report = render_analysis_report(self.spec, self.results, self.metadata)
        script = unselected_report.split("## 五、脚本分析", 1)[1].split("## 六、高光帧分析", 1)[0]
        self.assertIn("本次未选择该模块", script)
        self.assertNotIn("findings", script)

    def test_action_recommendations_and_gaps_stay_traceable_without_claim_duplication(self):
        results = [
            {"section": "material_ranking", "findings": [{
                "claim": "建议下一轮补充榜单指标对照实验。", "type": "recommendation", "confidence": "low",
                "fact_refs": ["facts/material-ranking.json#/records/0"],
            }], "gaps": ["缺少历史周期对照"], "next_questions": ["不同周期是否稳定？"]},
            self.results[1],
        ]
        report = render_analysis_report(self.spec, results, self.metadata)

        self.assertIn("## 二、行动建议", report)
        self.assertIn("建议下一轮补充榜单指标对照实验。 [E1]", report)
        self.assertIn("### 数据缺口与待验证问题", report)
        self.assertIn("数据缺口：缺少历史周期对照", report)
        self.assertIn("待验证问题：不同周期是否稳定？", report)
        body = report.split("## 附录 A：证据索引", 1)[0]
        self.assertEqual(body.count("建议下一轮补充榜单指标对照实验。"), 1)

    def test_cross_module_observation_is_only_rendered_for_cross_module_content(self):
        cross = dict(self.results[0], findings=[{
            "claim": "榜单与人群记录存在可进一步核验的关联。", "type": "inference", "confidence": "medium",
            "fact_refs": [
                "facts/material-ranking.json#/records/0",
                "facts/audience.json#/records/0",
            ],
        }])
        report = render_analysis_report(self.spec, [cross, self.results[1]], self.metadata)
        self.assertIn("## 七、跨模块观察", report)
        self.assertIn("榜单与人群记录存在可进一步核验的关联。 [E1] [E2]", report)

    def test_brand_proxy_explanation_is_concentrated_at_chapter_start_and_kept_in_audit(self):
        proxy_ref = "facts/audience.json#/records/0"
        metadata = dict(self.metadata, fact_index=dict(self.fact_index, **{
            proxy_ref: {
                "material_id": "101",
                "selection_group": {"brand_name": ""},
                "data_availability": {"selection_group": {"available": False}},
                "brand_classification": {
                    "source": "runtime_title_rule", "matchedBrands": ["品牌A"],
                },
            },
        }))
        proxy = {"section": "audience", "findings": [{
            "claim": "品牌A表现可进一步核验。", "type": "inference", "confidence": "medium",
            "fact_refs": [proxy_ref],
            "brand_proxy_explanation": "品牌名来自运行时标题规则，selection_group 未提供品牌名。",
        }]}
        report = render_analysis_report(self.spec, [self.results[0], proxy], metadata)
        body = report.split("## 附录 A：证据索引", 1)[0]
        audience = body.split("## 四、人群分析", 1)[1].split("## 五、脚本分析", 1)[0]

        self.assertEqual(audience.count("品牌名来自运行时标题规则"), 1)
        self.assertLess(audience.index("品牌代理说明"), audience.index("### 核心结论"))
        self.assertIn("品牌代理说明：品牌名来自运行时标题规则", report)

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
