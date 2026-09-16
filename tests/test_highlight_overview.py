import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.highlight_overview import HighlightOverviewError, build_highlight_overview, copy_verified_highlight_assets
from scripts.command_io import CommandFileCache


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class HighlightOverviewFixtureMixin:
    def make_run(self, directory):
        run_dir = Path(directory) / "run"
        (run_dir / "facts").mkdir(parents=True)
        (run_dir / "normalized/detail-records").mkdir(parents=True)
        (run_dir / "highlights/101").mkdir(parents=True)
        (run_dir / "highlights/102").mkdir(parents=True)
        (run_dir / "highlights/103").mkdir(parents=True)

        cards = [
            {
                "second": 0,
                "is_cover": True,
                "frame_type": "cover",
                "reasons": [{"type": "cover"}],
                "available": True,
                "relative_path": "highlights/101/01-000s.jpg",
            },
            {
                "second": 4,
                "is_cover": False,
                "frame_type": "custom_highlight",
                "reasons": [
                    {
                        "type": "top_values",
                        "trend_name": "点击指数",
                        "value": 0.88,
                        "rank": 2,
                        "within_high_point": False,
                    },
                    {
                        "type": "local_peak",
                        "trend_name": "点赞指数",
                        "value": 1.0,
                        "rank": 1,
                        "within_high_point": True,
                    },
                ],
                "available": True,
                "relative_path": "highlights/101/02-004s.jpg",
            },
        ]
        for relative_path, content in {
            "highlights/101/01-000s.jpg": b"cover-image",
            "highlights/101/02-004s.jpg": b"highlight-image",
        }.items():
            path = run_dir / relative_path
            path.write_bytes(content)

        unavailable = {
            "second": 2,
            "is_cover": False,
            "frame_type": "custom_highlight",
            "reasons": [{
                "type": "top_values",
                "trend_name": "点击指数",
                "value": 0.5,
                "rank": 3,
                "within_high_point": False,
            }],
            "available": False,
            "relative_path": "highlights/103/missing.jpg",
        }
        manifest_materials = [
            {"material_id": "101", "frames": cards},
            {"material_id": "102", "frames": [cards[0] | {"relative_path": "highlights/102/01-000s.jpg"}]},
            {"material_id": "103", "frames": [unavailable]},
        ]
        fact_materials = [
            {"material_id": "101", "frames": cards},
            {"material_id": "102", "frames": [cards[0] | {"relative_path": "highlights/102/01-000s.jpg"}]},
            {"material_id": "103", "frames": [unavailable]},
        ]
        ranking_path = run_dir / "facts/material-ranking.json"
        ranking_path.write_text(json.dumps({
            "schema_version": 1,
            "records": [
                {"material_id": "101", "title": "素材一"},
                {"material_id": "102"},
                {"material_id": "103", "title": "素材三"},
            ],
        }, ensure_ascii=False), encoding="utf-8")
        highlights_path = run_dir / "facts/highlight-frames.json"
        highlights_path.write_text(json.dumps({
            "schema_version": 1,
            "records": fact_materials,
        }, ensure_ascii=False), encoding="utf-8")
        manifest_path = run_dir / "highlights-manifest.json"
        manifest_path.write_text(json.dumps({
            "schemaVersion": 1,
            "materials": manifest_materials,
        }, ensure_ascii=False), encoding="utf-8")

        list_path = run_dir / "normalized/list-records.json"
        list_path.write_text("[]", encoding="utf-8")
        artifacts = {"listRecords": {
            "path": "normalized/list-records.json",
            "sha256": _sha256(list_path),
            "sizeBytes": list_path.stat().st_size,
        }}
        for material_id in ("101", "102", "103"):
            detail_path = run_dir / f"normalized/detail-records/{material_id}.json"
            detail_path.write_text(json.dumps({"material_id": material_id}), encoding="utf-8")
            artifacts[f"detailRecord:{material_id}"] = {
                "path": f"normalized/detail-records/{material_id}.json",
                "sha256": _sha256(detail_path),
                "sizeBytes": detail_path.stat().st_size,
            }
        (run_dir / "run-summary.json").write_text(json.dumps({
            "runId": "run-highlight-1",
            "collectionStatus": "success",
            "artifacts": artifacts,
        }), encoding="utf-8")
        (run_dir / "facts/manifest.json").write_text(json.dumps({
            "schema_version": 1,
            "run_id": "run-highlight-1",
            "packages": {
                "material_ranking": {
                    "path": "facts/material-ranking.json",
                    "record_count": 3,
                    "material_ids": ["101", "102", "103"],
                    "sha256": _sha256(ranking_path),
                },
                "highlight_frames": {
                    "path": "facts/highlight-frames.json",
                    "record_count": 3,
                    "material_ids": ["101", "102", "103"],
                    "sha256": _sha256(highlights_path),
                },
            },
        }), encoding="utf-8")
        return run_dir


class HighlightOverviewTests(HighlightOverviewFixtureMixin, unittest.TestCase):
    def test_copy_reuses_asset_index_and_streams_each_frame_once(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(directory)
            io_cache = CommandFileCache(run_dir)
            asset_index = {}
            model = build_highlight_overview(run_dir, io_cache=io_cache, asset_index=asset_index)
            output = run_dir / "overview-preview"
            before = {path: io_cache.read_count(path) for path in asset_index.values()}

            copied = copy_verified_highlight_assets(
                run_dir, output, model, io_cache=io_cache, asset_index=asset_index
            )

            self.assertEqual(copied, len(model["cards"]))
            for path in asset_index.values():
                self.assertEqual(io_cache.read_count(path), before[path] + 1)

    def test_projects_verified_cover_and_metric_cards_with_all_reasons(self):
        with tempfile.TemporaryDirectory() as directory:
            model = build_highlight_overview(self.make_run(directory))

        self.assertEqual(model["status"], "available")
        self.assertEqual(len(model["cards"]), 2)
        self.assertEqual(model["cards"][0]["role"], "视频开场画面")
        self.assertEqual(model["cards"][1]["role"], "指标高光帧")
        self.assertEqual(model["cards"][1]["frameIndex"], 2)
        self.assertEqual(len(model["cards"][1]["reasons"]), 2)
        self.assertEqual(model["cards"][1]["reasons"][0]["value"], 0.88)
        self.assertNotIn("clickCount", json.dumps(model, ensure_ascii=False))
        self.assertRegex(model["cards"][1]["assetPath"], r"^assets/highlights/[0-9a-f]{64}\.jpg$")

    def test_invalid_frames_and_missing_titles_become_gaps_without_cards(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(directory)
            manifest_path = run_dir / "highlights-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["materials"][0]["frames"][1]["relative_path"] = "../outside.jpg"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            model = build_highlight_overview(run_dir)

        self.assertEqual(len(model["cards"]), 1)
        self.assertEqual(
            {gap["code"] for gap in model["gaps"]},
            {"invalid_frame_path", "material_title_missing", "frame_unavailable"},
        )

    def test_unknown_reason_is_a_gap_and_does_not_create_a_fabricated_card(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(directory)
            facts_path = run_dir / "facts/highlight-frames.json"
            facts = json.loads(facts_path.read_text(encoding="utf-8"))
            facts["records"][0]["frames"][1]["reasons"][0] = {"type": "visual_inference"}
            facts_path.write_text(json.dumps(facts), encoding="utf-8")
            manifest_facts_path = run_dir / "facts/manifest.json"
            facts_manifest = json.loads(manifest_facts_path.read_text(encoding="utf-8"))
            facts_manifest["packages"]["highlight_frames"]["sha256"] = _sha256(facts_path)
            manifest_facts_path.write_text(json.dumps(facts_manifest), encoding="utf-8")
            manifest_path = run_dir / "highlights-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["materials"][0]["frames"][1]["reasons"][0] = {"type": "visual_inference"}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            model = build_highlight_overview(run_dir)

        self.assertEqual(len(model["cards"]), 1)
        self.assertIn("unknown_reason", {gap["code"] for gap in model["gaps"]})

    def test_manifest_package_hash_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(directory)
            path = run_dir / "facts/manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["packages"]["highlight_frames"]["sha256"] = "0" * 64
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(HighlightOverviewError, "highlight.*sha256"):
                build_highlight_overview(run_dir)

    def test_declared_frame_hash_and_size_mismatch_is_a_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = self.make_run(directory)
            manifest_path = run_dir / "highlights-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            frame = manifest["materials"][0]["frames"][0]
            frame["sha256"] = "0" * 64
            frame["sizeBytes"] = 999
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            model = build_highlight_overview(run_dir)

        self.assertEqual(len(model["cards"]), 1)
        self.assertIn("frame_hash_mismatch", {gap["code"] for gap in model["gaps"]})
        self.assertIn("frame_size_mismatch", {gap["code"] for gap in model["gaps"]})


if __name__ == "__main__":
    unittest.main()
