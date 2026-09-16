import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.single_material_overview import (
    SingleMaterialOverviewError,
    _project_formula,
    build_single_material_overview,
    copy_verified_single_material_assets,
)
from scripts.command_io import CommandFileCache


class SingleMaterialFixture:
    def __init__(self, root: Path, *, complete: bool = True):
        self.run = root / "run"
        (self.run / "facts").mkdir(parents=True)
        (self.run / "normalized/detail-records").mkdir(parents=True)
        (self.run / "highlights/101").mkdir(parents=True)
        self.material_ids = ["101", "102"]
        self._write_fixture(complete)

    def _write_json(self, relative: str, payload: object) -> bytes:
        path = self.run / relative
        content = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return content

    @staticmethod
    def _artifact(path: str, content: bytes) -> dict:
        return {"path": path, "sha256": hashlib.sha256(content).hexdigest(), "sizeBytes": len(content)}

    def _write_fixture(self, complete: bool) -> None:
        ranking = [
            {"material_id": "101", "rank": 2, "title": "详情素材", "publish_time": "20260820", "video_duration": 8,
             "people_tags": ["精致妈妈"], "material_tags": ["口播"], "metrics": {"show_cnt": 20, "ctr": 0.2}},
            {"material_id": "102", "rank": 1, "title": "另一详情", "publish_time": "20260821", "video_duration": 9,
             "people_tags": [], "material_tags": [], "metrics": {"show_cnt": 10}},
            {"material_id": "999", "rank": 3, "title": "榜单但无详情", "metrics": {"show_cnt": 99}},
        ]
        audience = [{"material_id": material_id, "observations": [{"dimension": "crowd_group", "tag": "精致妈妈"}],
                     "data_availability": {"available": True, "missing_reason": ""}} for material_id in (self.material_ids + ["999"])]
        interaction = []
        script = []
        frames = []
        for material_id in self.material_ids:
            trends = [{"trend_name": name, "series": [{"second": 0, "value": 0.1}, {"second": 1, "value": 0.2}]}
                       for name in ("点赞指数", "流失指数", "点击指数", "互动指数", "评论指数")]
            interaction.append({"material_id": material_id, "trend_series": trends,
                                "data_availability": {"trends": {"available": True, "missing_reason": ""}}})
            formula = {"labels": [{"level_1_label": 10, "level_2_labels": [52]}],
                       "sources": {"title": {"text": "标题原文", "detail": {"52": ["词项"]}},
                                   "visual": {"text": "画面原文", "detail": {}},
                                   "script": {"text": "脚本原文", "detail": {"52": ["脚本词"]}}}}
            script.append({"material_id": material_id, "audience_portrait": {"eightCrowds": ["精致妈妈"], "ageFeatures": [], "genderFeatures": ["女"]},
                           "script_text": "脚本文本", "content_formula": formula if complete else {"labels": []},
                           "creative_breakdown": {"tags": ["口播"]},
                           "data_availability": {"audience_portrait": {"available": True, "missing_reason": ""},
                                                  "script_text": {"available": True, "missing_reason": ""},
                                                  "content_formula": {"available": True, "missing_reason": ""}}})
            frame_path = f"highlights/101/{material_id}.jpg"
            image = b"fixture-image-" + material_id.encode()
            (self.run / frame_path).write_bytes(image)
            frame = {"second": 0, "is_cover": True, "frame_type": "cover", "reasons": [{"type": "cover"}],
                     "available": True, "frame_ref": f"highlight:{material_id}:cover:0", "relative_path": frame_path}
            frames.append({"material_id": material_id, "frames": [frame], "data_availability": {}})

        package_payloads = {
            "material-ranking.json": ranking,
            "audience.json": audience,
            "interaction-series.json": interaction,
            "script.json": script,
            "highlight-frames.json": frames,
        }
        packages = {}
        for filename, records in package_payloads.items():
            content = self._write_json(f"facts/{filename}", {"records": records})
            name = filename[:-5].replace("-", "_")
            packages[name] = {"path": f"facts/{filename}", "record_count": len(records),
                              "material_ids": [record["material_id"] for record in records],
                              "sha256": hashlib.sha256(content).hexdigest(), "sizeBytes": len(content)}
        detail_artifacts = {}
        for material_id in self.material_ids:
            detail = {"material_id": material_id, "title": "详情素材", "video_url": "https://external.invalid/video.mp4"}
            content = self._write_json(f"normalized/detail-records/{material_id}.json", detail)
            detail_artifacts[f"detailRecord:{material_id}"] = self._artifact(f"normalized/detail-records/{material_id}.json", content)
        list_content = self._write_json("normalized/list-records.json", ranking)
        highlights_content = self._write_json("highlights-manifest.json", {"schemaVersion": 2, "materials": frames})
        self._write_json("run-summary.json", {
            "runId": "fixture-run", "status": "ready_for_analysis", "collectionStatus": "success",
            "artifacts": {"listRecords": self._artifact("normalized/list-records.json", list_content), **detail_artifacts},
            "taskRuns": {f"detail:{material_id}": {"operation": "detail", "status": "persisted", "material_id": material_id}
                         for material_id in self.material_ids},
        })
        source_artifacts = [self._artifact("normalized/list-records.json", list_content), self._artifact("highlights-manifest.json", highlights_content)]
        source_artifacts.extend(self._artifact(f"normalized/detail-records/{material_id}.json", (self.run / f"normalized/detail-records/{material_id}.json").read_bytes()) for material_id in self.material_ids)
        manifest = {"schema_version": 3, "run_id": "fixture-run", "coverage": {"ranking_records": 3, "detail_records": 2, "highlight_materials": 2},
                    "packages": packages, "source_artifacts": source_artifacts}
        self._write_json("facts/manifest.json", manifest)


class SingleMaterialOverviewTests(unittest.TestCase):
    def test_copy_reuses_asset_index_and_streams_each_asset_once(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = SingleMaterialFixture(Path(directory))
            video = fixture.run / "videos/101/source-video.mp4"
            video.parent.mkdir(parents=True)
            video.write_bytes(b"verified-video")
            io_cache = CommandFileCache(fixture.run)
            asset_index = {}
            model = build_single_material_overview(
                fixture.run, io_cache=io_cache, asset_index=asset_index
            )
            output = fixture.run / "overview-preview"
            before = {path: io_cache.read_count(path) for path in asset_index.values()}

            copied = copy_verified_single_material_assets(
                fixture.run,
                output,
                model,
                io_cache=io_cache,
                asset_index=asset_index,
            )

            self.assertEqual(copied, 3)
            self.assertTrue(asset_index)
            for path in asset_index.values():
                self.assertEqual(io_cache.read_count(path), before[path] + 1)

    def test_real_run_selects_only_persisted_detail_materials_and_projects_every_module(self):
        root = Path(__file__).resolve().parents[1]
        model = build_single_material_overview(root / "runs/food-drink-exposure-20260820-27-top10")

        self.assertEqual(model["materialCount"], 10)
        self.assertEqual([item["rank"] for item in model["materials"]], list(range(1, 11)))
        self.assertEqual(model["source"]["verifiedFrameCount"], 56)
        self.assertEqual(len(model["materials"][0]["trends"]["metrics"]), 5)
        self.assertEqual(model["materials"][0]["publishTime"], "20260817")
        self.assertEqual(model["materials"][0]["core"]["defaultFieldIds"], [
            "metrics.show_cnt", "metrics.play_3s_rate", "metrics.play_over_rate",
            "metrics.ctr", "metrics.cvr", "metrics.pvr", "metrics.interact_rate",
        ])
        self.assertNotIn("title", {field["id"] for field in model["materials"][0]["core"]["fields"]})
        self.assertNotIn("publish_time", {field["id"] for field in model["materials"][0]["core"]["fields"]})
        self.assertNotIn("video_duration", {field["id"] for field in model["materials"][0]["core"]["fields"]})
        self.assertNotIn("rank", {field["id"] for field in model["materials"][0]["core"]["fields"]})
        self.assertFalse(model["materials"][0]["video"]["available"])
        self.assertIn("local_video_artifact_missing", model["materials"][0]["video"]["reason"])
        serialized = json.dumps(model, ensure_ascii=False)
        self.assertNotIn("https://", serialized)
        self.assertNotIn("normalized/detail-records", serialized)
        self.assertNotIn("999", {item["materialId"] for item in model["materials"]})

    def test_real_run_core_fields_include_detail_rates_and_exclude_component_click_rate(self):
        root = Path(__file__).resolve().parents[1]
        fields = build_single_material_overview(root / "runs/food-drink-exposure-20260820-27-top10")["materials"][0]["core"]["fields"]
        field_ids = {field["id"] for field in fields}

        self.assertNotIn("metrics.play_duration_avg", field_ids)
        self.assertTrue({
            "metrics.like_rate",
            "metrics.comment_rate",
            "metrics.share_rate",
            "metrics.product_wish_button_buy_cart_rate",
        }.issubset(field_ids))
        self.assertNotIn("metrics.component_click_rate", field_ids)
        values = {field["id"]: field["value"] for field in fields}
        self.assertEqual(values["metrics.like_rate"], 0.0)
        self.assertEqual(values["metrics.comment_rate"], 0.0001054136)
        self.assertEqual(values["metrics.share_rate"], 0.0003116175)
        self.assertEqual(values["metrics.product_wish_button_buy_cart_rate"], 0.0)

    def test_hash_mismatch_rejects_detail_source_before_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = SingleMaterialFixture(Path(directory))
            detail = fixture.run / "normalized/detail-records/101.json"
            detail.write_text(detail.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with self.assertRaisesRegex(SingleMaterialOverviewError, "sha256|size"):
                build_single_material_overview(fixture.run)

    def test_highlight_fact_and_manifest_join_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = SingleMaterialFixture(Path(directory))
            manifest_path = fixture.run / "highlights-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["materials"][0]["frames"][0]["second"] = 3
            content = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode()
            manifest_path.write_bytes(content)
            facts_manifest_path = fixture.run / "facts/manifest.json"
            facts_manifest = json.loads(facts_manifest_path.read_text(encoding="utf-8"))
            for item in facts_manifest["source_artifacts"]:
                if item["path"] == "highlights-manifest.json":
                    item["sha256"] = hashlib.sha256(content).hexdigest()
                    item["sizeBytes"] = len(content)
            facts_manifest_path.write_text(json.dumps(facts_manifest, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            with self.assertRaisesRegex(SingleMaterialOverviewError, "binding"):
                build_single_material_overview(fixture.run)

    def test_formula_links_use_explicit_ids_and_missing_modules_stay_local(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = SingleMaterialFixture(Path(directory), complete=True)
            model = build_single_material_overview(fixture.run)
            material = model["materials"][0]
        self.assertEqual(material["formula"]["links"][0]["id"], "52")
        self.assertEqual(material["formula"]["links"][0]["source"], "title")
        self.assertEqual(material["formula"]["links"][0]["texts"], ["词项"])
        self.assertEqual(material["creative"]["status"], "deferred")
        self.assertEqual(material["portrait"]["status"], "available")

    def test_empty_formula_source_is_unavailable_without_affecting_other_modules(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = SingleMaterialFixture(Path(directory), complete=False)
            model = build_single_material_overview(fixture.run)
        material = model["materials"][0]
        self.assertEqual(material["formula"]["status"], "unavailable")
        self.assertEqual(material["trends"]["status"], "available")
        self.assertEqual(material["creative"]["status"], "deferred")

    def test_unknown_formula_ids_are_projected_dynamically(self):
        script = {
            "script_text": "原始脚本文案",
            "content_formula": {
                "labels": [{"level_1_label": 9, "level_2_labels": [888888]}],
                "sources": {"script": {"text": "原始脚本文案", "detail": {"888888": ["动态词项"]}}},
            },
            "data_availability": {"content_formula": {"available": True, "missing_reason": ""}},
        }
        projected = _project_formula(script)
        self.assertEqual(projected["status"], "available")
        self.assertEqual(projected["labels"], [{
            "id": "9",
            "label": "商品卖点",
            "secondary": [{"id": "888888", "label": "动态词项"}],
        }])
        self.assertEqual(projected["sources"]["script"]["text"], "原始脚本文案")
        self.assertEqual(projected["links"][0]["id"], "888888")

    def test_copy_verified_assets_is_hash_bound_and_writes_only_preview_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = SingleMaterialFixture(Path(directory))
            model = build_single_material_overview(fixture.run)
            output = fixture.run / "overview-preview"
            copied = copy_verified_single_material_assets(fixture.run, output, model)
            self.assertEqual(copied, 2)
            for material in model["materials"]:
                for frame in material["highlights"]["frames"]:
                    target = output / frame["assetPath"]
                    self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), frame["assetSha256"])
                    self.assertEqual(target.stat().st_size, frame["assetSizeBytes"])


if __name__ == "__main__":
    unittest.main()
