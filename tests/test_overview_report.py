import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.overview_report import (
    OverviewReportError,
    build_overview_data,
    render_overview_html,
    write_overview,
)


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config/yuntu-material-field-registry-v1.json"


class OverviewFixtureMixin:
    def make_run(self, directory, rows=None):
        run_dir = Path(directory) / "run"
        (run_dir / "normalized").mkdir(parents=True)
        (run_dir / "facts").mkdir()
        rows = rows or [
            {
                "material_id": "101",
                "item_id": "secret-item",
                "account_id": "secret-account",
                "title": "甲素材 <测试>",
                "rank": 2,
                "publish_time": "20260821",
                "video_duration": 12,
                "material_uri": "video-code-101",
                "people_tags": ["精致妈妈", "女"],
                "material_tags": ["多人情景剧"],
                "metrics": {
                    "show_cnt": 30,
                    "play_3s_rate": 0.3,
                    "play_5s_rate": 0.2,
                    "play_over_rate": 0.1,
                    "ctr": 0.02,
                    "component_click_rate": 0.01,
                    "cvr": 0.03,
                    "pvr": 0.004,
                    "interact_rate": 0.005,
                    "play_duration_avg": 99,
                },
                "list_context": {"account_id": "secret-account"},
            },
            {
                "material_id": "102",
                "title": "乙素材",
                "rank": 1,
                "publish_time": "20260820",
                "video_duration": 20,
                "metrics": {"show_cnt": 10, "play_over_rate": 0.9},
                "people_tags": [],
                "material_tags": [],
            },
            {
                "material_id": "103",
                "title": "丙素材",
                "rank": 3,
                "publish_time": "20260822",
                "metrics": {"show_cnt": None, "play_over_rate": 0.1},
                "people_tags": ["小镇青年"],
                "material_tags": ["口播"],
            },
        ]
        source_path = run_dir / "normalized/list-records.json"
        source_path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        source_bytes = source_path.read_bytes()
        run_id = "run-fixture-1"
        (run_dir / "run-summary.json").write_text(json.dumps({
            "schemaVersion": 2,
            "runId": run_id,
            "collectionStatus": "success",
            "status": "success",
            "stages": {"list": {
                "requestStatus": "requested",
                "normalized": True,
                "contextVerified": True,
            }},
            "artifacts": {"listRecords": {
                "path": "normalized/list-records.json",
                "sha256": hashlib.sha256(source_bytes).hexdigest(),
                "sizeBytes": len(source_bytes),
                "parseStatus": "succeeded",
            }},
        }, ensure_ascii=False), encoding="utf-8")
        (run_dir / "batch-manifest.json").write_text(json.dumps({
            "schemaVersion": 2,
            "runId": run_id,
            "status": "success",
            "candidateTopN": len(rows),
            "collectionContract": {"candidateTopN": len(rows), "targetTopN": 1},
        }), encoding="utf-8")
        (run_dir / "facts/manifest.json").write_text(json.dumps({
            "schema_version": 3,
            "run_id": run_id,
            "coverage": {"ranking_records": len(rows)},
        }), encoding="utf-8")
        (run_dir / "resolved-query-spec.json").write_text(json.dumps({
            "schema_version": 1,
            "industry": "食品饮料",
            "period": {"type": "CUSTOM", "start_date": "2026-08-20", "end_date": "2026-08-27"},
            "filters": {
                "ages": [], "genders": [], "crowd_groups": [],
                "brand_scope": {"type": "ALL_INDUSTRY", "brands": []},
            },
            "ranking": {"metric": "EXPOSURE_TOP1000"},
            "material_list": {"sort": {"field": "rank", "direction": "asc"}},
        }, ensure_ascii=False), encoding="utf-8")
        return run_dir


class OverviewDataTests(OverviewFixtureMixin, unittest.TestCase):
    def test_build_overview_projects_all_verified_list_rows_and_yuntu_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(directory)
            model = build_overview_data(run_dir, REGISTRY)

        self.assertEqual(model["kind"], "yuntu_material_leaderboard_overview")
        self.assertEqual(model["runId"], "run-fixture-1")
        self.assertEqual(model["source"]["recordCount"], 3)
        self.assertEqual(len(model["rows"]), 3)
        self.assertEqual(model["rows"][0]["values"]["metrics.show_cnt"], 30)
        self.assertEqual(model["rows"][0]["values"]["metrics.play_over_rate"], 0.1)
        self.assertEqual(model["rows"][0]["values"]["people_tags"], ["精致妈妈", "女"])
        self.assertEqual(next(field for field in model["fields"] if field["id"] == "metrics.show_cnt")["label"], "曝光量")
        self.assertEqual(next(field for field in model["fields"] if field["id"] == "metrics.play_over_rate")["label"], "完播率")
        self.assertNotIn("material_id", {field["id"] for field in model["fields"]})
        self.assertEqual(model["defaultFieldIds"], [
            "title", "publish_time", "metrics.show_cnt", "metrics.play_3s_rate",
            "metrics.play_over_rate", "metrics.ctr", "metrics.cvr", "metrics.pvr",
            "metrics.interact_rate",
        ])
        self.assertNotIn("account_id", json.dumps(model, ensure_ascii=False))
        self.assertNotIn("list_context", json.dumps(model, ensure_ascii=False))

    def test_build_overview_rejects_run_summary_hash_or_count_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(directory)
            source_path = run_dir / "normalized/list-records.json"
            source_path.write_text(source_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with self.assertRaisesRegex(OverviewReportError, "sha256|size"):
                build_overview_data(run_dir, REGISTRY)

    def test_build_overview_rejects_escaped_source_and_duplicate_material_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(directory)
            summary_path = run_dir / "run-summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["artifacts"]["listRecords"]["path"] = "../normalized/list-records.json"
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaisesRegex(OverviewReportError, "relative|inside|path"):
                build_overview_data(run_dir, REGISTRY)

        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(directory, rows=[{"material_id": "1"}, {"material_id": "1"}])
            with self.assertRaisesRegex(OverviewReportError, "duplicate"):
                build_overview_data(run_dir, REGISTRY)

    def test_build_overview_redacts_sensitive_material_list_filter_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(directory)
            query_path = run_dir / "resolved-query-spec.json"
            query = json.loads(query_path.read_text(encoding="utf-8"))
            query["material_list"]["filters"] = [
                {"field": "account_id", "operator": "eq", "value": "secret-account"},
                {"field": "曝光量", "operator": "gte", "value": 10},
            ]
            query_path.write_text(json.dumps(query, ensure_ascii=False), encoding="utf-8")
            model = build_overview_data(run_dir, REGISTRY)
        self.assertNotIn("account_id", json.dumps(model, ensure_ascii=False))
        self.assertEqual(model["queryContext"]["materialList"]["filters"], [
            {"field": "曝光量", "operator": "gte", "value": 10},
        ])


class OverviewHtmlTests(OverviewFixtureMixin, unittest.TestCase):
    def test_real_overview_contains_audience_and_formula_sections(self):
        run_dir = ROOT / "runs/food-drink-exposure-20260820-27-top10"
        model = build_overview_data(run_dir, REGISTRY)
        html = render_overview_html(model)
        self.assertEqual(model["scriptFormulaOverview"]["coverage"]["formulaMaterialCount"], 2)
        self.assertIn('data-section="audience"', html)
        self.assertIn('data-section="scripts"', html)
        self.assertIn("renderAudience", html)
        self.assertIn("renderScriptFormula", html)
        self.assertIn("secondaryBucketsByPrimary", html)
        self.assertIn("max-width:1120px", html)
        self.assertIn(".audience-card", html)
        self.assertIn(".donut-layout", html)
        self.assertIn("grid-template-columns:repeat(2,minmax(0,1fr))", html)
        self.assertIn(".donut-layout .chart-box", html)
        self.assertIn(".chart-grid > .chart-card .donut-layout { flex:1; }", html)
        self.assertNotIn("audience-material-count", html)
        self.assertIn(".script-formula-svg", html)
        self.assertIn("script-card-header", html)
        self.assertIn("script-formula-donut", html)
        self.assertNotIn("fetch(", html)

    def test_rendered_html_has_qianchuan_style_dialog_fixed_title_and_page_size(self):
        with tempfile.TemporaryDirectory() as directory:
            model = build_overview_data(self.make_run(directory), REGISTRY)
            html = render_overview_html(model)

        self.assertIn('id="field-button" type="button">自定义指标</button>', html)
        self.assertIn('role="dialog"', html)
        self.assertIn('id="field-groups"', html)
        self.assertIn('id="field-options"', html)
        self.assertIn('id="selected-fields"', html)
        self.assertIn('data-field-action="confirm"', html)
        self.assertIn("素材ID：", html)
        self.assertIn('class="material-name-column"', html)
        self.assertIn("const pageSize = 10;", html)
        self.assertIn("localStorage", html)
        self.assertIn("field.sortable", html)
        self.assertIn("NFKC", html)
        self.assertLess(html.index('field.id === "video_duration"'), html.index('field.valueType === "number"'))
        self.assertIn(
            'if (missing(left.values[field.id]) || missing(right.values[field.id])) return compareValues(left.values[field.id], right.values[field.id], field);',
            html,
        )

    def test_rendered_html_is_offline_and_has_no_sensitive_or_analysis_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            model = build_overview_data(self.make_run(directory), REGISTRY)
            html = render_overview_html(model)

        self.assertNotIn("fetch(", html)
        self.assertNotIn("AI 分析", html)
        self.assertNotIn("行动建议", html)
        self.assertNotIn("https://", html)
        self.assertNotIn("account_id", html)
        self.assertNotIn("/Users/", html)
        self.assertIn("\\u003c", html)

    def test_write_overview_only_publishes_two_artifacts_and_returns_redacted_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(directory)
            output_dir = run_dir / "overview-preview"
            receipt = write_overview(run_dir, output_dir, REGISTRY)
            self.assertEqual(sorted(path.name for path in output_dir.iterdir()), ["index.html", "overview-data.json"])
            self.assertEqual(receipt["status"], "succeeded")
            self.assertEqual(receipt["recordCount"], 3)
            self.assertNotIn(str(run_dir), json.dumps(receipt))
            self.assertNotIn("account", json.dumps(receipt).lower())
