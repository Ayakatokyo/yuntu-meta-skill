import hashlib
import json
import shutil
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
    def install_content_tags_package(self, run_dir, records):
        package_path = run_dir / "facts/content-tags.json"
        package_path.write_text(json.dumps({"schema_version": 1, "records": records}, ensure_ascii=False), encoding="utf-8")
        manifest_path = run_dir / "facts/manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["packages"] = {
            "content_tags": {
                "path": "facts/content-tags.json",
                "record_count": len(records),
                "material_ids": [str(record["material_id"]) for record in records],
                "source_paths": ["normalized/list-records.json", "raw-csv/list.csv"],
                "sha256": hashlib.sha256(package_path.read_bytes()).hexdigest(),
            }
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    def test_build_overview_includes_material_coverage_marketing_selling_points(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(directory)
            self.install_content_tags_package(run_dir, [
                {
                    "material_id": "101",
                    "platform_content_tags": ["成分配方原料_燕窝", "功效功能_滋补", "真人有语音商品展示"],
                    "data_availability": {"material_tags": {"available": True, "missing_reason": ""}},
                    "source_paths": {"normalized": "normalized/list-records.json"},
                },
                {
                    "material_id": "102",
                    "platform_content_tags": ["成分配方原料_燕窝", "使用场景_送礼"],
                    "data_availability": {"material_tags": {"available": True, "missing_reason": ""}},
                    "source_paths": {"normalized": "normalized/list-records.json"},
                },
                {
                    "material_id": "103",
                    "platform_content_tags": [],
                    "data_availability": {"material_tags": {"available": False, "missing_reason": "source_empty"}},
                    "source_paths": {"normalized": "normalized/list-records.json"},
                },
            ])
            model = build_overview_data(run_dir, REGISTRY)

        overview = model["marketingSellingPointOverview"]
        self.assertEqual(overview["status"], "available")
        self.assertEqual(overview["coverage"]["marketingSellingPointMaterialCount"], 2)
        primary = {item["label"]: item for item in overview["primaryBuckets"]}
        self.assertEqual(primary["成分配方原料"]["value"], 2)
        self.assertNotIn("真人有语音商品展示", primary)
        self.assertEqual(
            {item["label"]: item["value"] for item in overview["secondaryBucketsByPrimary"]["成分配方原料"]},
            {"燕窝": 2},
        )
        self.assertNotIn("未细分", overview["secondaryBucketsByPrimary"])

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
    def test_overview_copies_verified_local_video_and_renders_a_9_by_16_player(self):
        source_run = ROOT / "runs/food-drink-exposure-20260820-27-top10"
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            shutil.copytree(source_run, run_dir)
            material_id = "7668663443726172214"
            source_video = run_dir / "videos" / material_id / "source-video.mp4"
            source_video.parent.mkdir(parents=True)
            source_video.write_bytes(b"verified local video")

            model = build_overview_data(run_dir, REGISTRY)
            material = next(item for item in model["singleMaterialOverview"]["materials"] if item["materialId"] == material_id)
            html = render_overview_html(model)
            result = write_overview(run_dir, run_dir / "overview-with-video", REGISTRY)

            self.assertTrue(material["video"]["available"])
            self.assertEqual(material["video"]["assetPath"], "assets/single-material/videos/7668663443726172214.mp4")
            self.assertEqual((run_dir / "overview-with-video" / material["video"]["assetPath"]).read_bytes(), b"verified local video")
            self.assertIn("<video", html)
            self.assertIn("aspect-ratio:9 / 16", html)
            self.assertIn(".single-material-video { display:flex; width:min(100%,140px);", html)
            self.assertIn('<video controls preload="metadata"', html)
            self.assertNotIn(".single-material-video { min-height:140px; aspect-ratio:auto; }", html)
            self.assertIn("overview-with-video/index.html", result["outputPaths"])

    def test_real_overview_contains_audience_and_formula_sections(self):
        run_dir = ROOT / "runs/food-drink-exposure-20260820-27-top10"
        model = build_overview_data(run_dir, REGISTRY)
        html = render_overview_html(model)
        self.assertEqual(model["scriptFormulaOverview"]["coverage"]["formulaMaterialCount"], 2)
        self.assertEqual(model["scriptFormulaOverview"]["source"]["taxonomyVersion"], "yuntu-content-formula-taxonomy-v1")
        self.assertEqual(model["marketingSellingPointOverview"]["status"], "available")
        self.assertGreater(model["marketingSellingPointOverview"]["coverage"]["marketingSellingPointMaterialCount"], 0)
        self.assertNotIn('"41"', json.dumps(model["scriptFormulaOverview"], ensure_ascii=False))
        self.assertEqual(model["highlightOverview"]["status"], "available")
        self.assertEqual(model["highlightOverview"]["source"]["verifiedFrameCount"], 56)
        self.assertEqual(len(model["highlightOverview"]["cards"]), 56)
        self.assertNotIn("normalized/detail-records", json.dumps(model["highlightOverview"], ensure_ascii=False))
        self.assertIn('data-section="audience"', html)
        self.assertIn('data-section="scripts"', html)
        self.assertIn('data-section="marketing-selling-points"', html)
        self.assertIn('data-section="highlights"', html)
        self.assertIn('id="highlights-panel"', html)
        self.assertIn("renderAudience", html)
        self.assertIn("renderScriptFormula", html)
        self.assertIn("renderMarketingSellingPoints", html)
        self.assertIn("renderHighlights", html)
        self.assertIn("const highlightPageSize = 12;", html)
        self.assertNotIn('id="highlight-summary"', html)
        self.assertNotIn("已验证图片", html)
        self.assertIn("aspect-ratio:9 / 16", html)
        self.assertIn("object-fit:contain", html)
        self.assertIn("function highlightDescription", html)
        self.assertIn("function highlightConditionLabel", html)
        self.assertIn("function highlightValueLabel", html)
        self.assertIn("highlight-conditions", html)
        self.assertIn("highlight-values", html)
        self.assertIn('reason.type === "top_values" ? "数值" : "波峰"', html)
        self.assertIn("${reason.trend_name}${kind}Top${reason.rank}", html)
        self.assertIn("${second}s · ${reason.trend_name} ${value}", html)
        self.assertIn("text-align:center", html)
        self.assertIn("justify-content:center", html)
        self.assertIn("color:var(--text)", html)
        self.assertIn(".highlight-condition", html)
        self.assertIn(".highlight-value", html)
        self.assertIn(".highlight-condition { color:var(--text); font-size:12px", html)
        self.assertIn(".highlight-value { color:var(--muted); font-size:12px", html)
        self.assertNotIn('class=\"highlight-reason\"', html)
        self.assertNotIn("波峰画面", html)
        self.assertNotIn("replace(/指数$/, \"\")", html)
        self.assertNotIn("角色：", html)
        self.assertIn("openHighlightModal", html)
        self.assertIn("data-highlight-material-id", html)
        self.assertIn('<a href="#single-material-data" class="highlight-material"', html)
        self.assertIn("overflow-wrap:anywhere", html)
        self.assertIn("white-space:normal", html)
        self.assertIn("state.pendingMaterialId", html)
        self.assertIn('new CustomEvent("yuntu:highlight-material"', html)
        self.assertIn("event.preventDefault()", html)
        self.assertNotIn('document.querySelector(\'[data-section="materials"]\').click()', html)
        self.assertIn("highlight-modal", html)
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
        self.assertIn("function setScriptFormulaSelection", html)
        self.assertIn("data-script-formula-angle", html)
        self.assertIn("item.setAttribute(\"aria-pressed\", String(selected))", html)
        self.assertIn("Math.cos(angle) * distance", html)
        self.assertIn("marketingSellingPointOverview", html)
        self.assertIn("一级营销卖点", html)
        self.assertIn("二级营销卖点分布", html)
        self.assertNotIn("fetch(", html)

    def test_real_overview_contains_detail_scoped_single_material_workbench(self):
        run_dir = ROOT / "runs/food-drink-exposure-20260820-27-top10"
        model = build_overview_data(run_dir, REGISTRY)
        html = render_overview_html(model)

        single = model["singleMaterialOverview"]
        self.assertEqual(single["materialCount"], 10)
        self.assertEqual(single["source"]["verifiedFrameCount"], 56)
        self.assertEqual(len(single["materials"][0]["trends"]["metrics"]), 5)
        self.assertEqual(len(single["materials"][0]["highlights"]["frames"]), 6)
        self.assertEqual(model["highlightFilterContext"], [
            {"label": "封面帧", "value": "包含"},
            {"label": "点赞指数", "value": "数值 Top，2 帧"},
            {"label": "流失指数", "value": "局部峰值，2 帧"},
            {"label": "点击指数", "value": "数值 Top，2 帧"},
        ])
        self.assertIn('data-section="filters"', html)
        self.assertLess(html.index('data-section="filters"'), html.index('data-section="materials"'))
        self.assertIn('id="filters-panel"', html)
        self.assertIn('id="filter-config"', html)
        self.assertIn("renderFilterConfig", html)
        self.assertIn("filter-config-layout", html)
        self.assertIn("filter-config-shell", html)
        self.assertIn("素材列表筛选条件", html)
        self.assertIn("高光帧筛选标准", html)
        self.assertIn("highlightFilterContext", html)
        self.assertIn("filterConfigHasValue", html)
        self.assertIn("曝光量 Top1000", html)
        self.assertIn("近7天", html)
        self.assertIn("指定品牌", html)
        self.assertNotIn('data-section="single-material-data" class="active"', html)
        self.assertIn('data-section="single-material-data"', html)
        self.assertLess(html.index('data-section="highlights"'), html.index('data-section="single-material-data"'))
        self.assertIn('id="single-material-data-panel"', html)
        self.assertIn('data-material-selector', html)
        self.assertNotIn('data-material-tab="filters"', html)
        self.assertNotIn('aria-controls="single-material-filters"', html)
        self.assertIn('data-material-tab="core"', html)
        self.assertIn('data-material-tab="portrait"', html)
        self.assertIn('data-material-tab="trends"', html)
        self.assertIn('data-material-tab="formula"', html)
        self.assertNotIn('data-material-tab="creative"', html)
        self.assertIn('data-material-tab="highlights"', html)
        self.assertIn('aria-controls="single-material-core"', html)
        self.assertIn("position:sticky; top:0", html)
        self.assertIn("scrollIntoView({behavior:\"smooth\", block:\"start\"})", html)
        section_navigation = html.split('document.querySelectorAll("[data-section]")', 1)[1].split('document.querySelectorAll("[data-material-tab]")', 1)[0]
        self.assertIn('renderSingleMaterial();', section_navigation)
        self.assertIn('setSingleMaterialTab("core");', section_navigation)
        self.assertIn('renderFilterConfig();', section_navigation)
        self.assertNotIn('single-material-data-panel', section_navigation)
        self.assertNotIn('scrollIntoView', section_navigation)
        self.assertNotIn(".single-material-panel[hidden]", html)
        self.assertIn("local_video_artifact_missing", html)
        self.assertIn("singleTrendSpan", html)
        self.assertIn("singleTrendSpanValue", html)
        self.assertIn("if (metric) renderSingleTrendChart(metric);", html)
        self.assertIn('data-single-range="span"', html)
        self.assertNotIn("singleTrendStart", html)
        self.assertNotIn("singleTrendEnd", html)
        self.assertIn("setFormulaSelection", html)
        self.assertIn("single-core-field-button", html)
        self.assertIn("single-core-field-management", html)
        self.assertIn("single-core-field-groups", html)
        self.assertIn("singleCoreFixedFields", html)
        self.assertIn('const singleCoreFixedFields = [];', html)
        self.assertIn('const singleCoreFieldGroupOrder = ["展现指标", "互动/种草指标", "转化指标"];', html)
        for removed_field in ("fixed.video_code", "fixed.audience", "fixed.material_tags", "fixed.rank", "fixed.video_duration"):
            self.assertNotIn(removed_field, html)
        self.assertIn("singleCoreStorageKey", html)
        self.assertIn("榜单排名：${material.rank} · 首投日期：${material.publishTime || \"—\"}", html)
        self.assertNotIn("仅展示本 run 已完成详情 RPA 且通过 facts 校验的素材。", html)
        self.assertIn("publishTime", json.dumps(single, ensure_ascii=False))
        self.assertIn("single-portrait-grid", html)
        self.assertIn("ensureSinglePanelHeadings", html)
        for panel_title in ("素材筛选条件", "核心数据", "人群画像", "秒级拆解", "内容公式", "高光帧数据"):
            self.assertIn(panel_title, html)
        self.assertNotIn('id="single-material-creative"', html)
        self.assertNotIn("创意元素拆解", html)
        self.assertIn("single-formula-flow", html)
        self.assertIn("single-formula-primary", html)
        self.assertIn("single-formula-secondary-list", html)
        self.assertIn("formulaSourceText", html)
        self.assertIn("本视频脚本文案", html)
        self.assertIn("single-script-highlight", html)
        self.assertIn("点击内容公式或下方脚本文案，可双向定位", html)
        self.assertNotIn("最多 2 帧", html)
        self.assertIn("singleHighlightPageSize = 8", html)
        self.assertIn("grid-template-columns:repeat(4,minmax(0,1fr))", html)
        self.assertIn("single-material-overview", html)
        self.assertIn("grid-template-columns:minmax(140px,18%) minmax(0,1fr)", html)
        self.assertIn('document.querySelector(".single-material-main")?.scrollIntoView({behavior:"auto", block:"start"})', html)
        self.assertIn(".single-trend-chart { width:100%", html)
        self.assertIn(".single-trend-chart svg { display:block; width:100%; min-width:100%; height:230px; }", html)
        self.assertIn("overflow:hidden", html)
        self.assertIn("width = 640", html)
        self.assertIn("left = 8, right = 8", html)
        self.assertIn('preserveAspectRatio=\"none\"', html)
        self.assertLess(html.index('id=\"single-trend-chart\"'), html.index('id=\"singleTrendSpan\"'))
        self.assertIn("本阶段暂未设计", html)
        self.assertNotIn("video_url", html)
        for label in ("首页", "上一页", "下一页", "尾页"):
            self.assertIn(f">{label}<", html)
        for label in (">首<", ">前<", ">后<", ">末<"):
            self.assertNotIn(label, html)

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
