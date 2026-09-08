import hashlib
import json
import shutil
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from scripts.script_formula_overview import (
    ScriptFormulaOverviewError,
    _load_taxonomy,
    build_script_formula_overview,
)


ROOT = Path(__file__).resolve().parents[1]


class ScriptFormulaOverviewTests(unittest.TestCase):
    def make_script_run(self, labels_by_record, taxonomy=None):
        temp_dir = tempfile.TemporaryDirectory()
        run_dir = Path(temp_dir.name) / "run"
        shutil.copytree(ROOT / "runs/food-drink-exposure-20260820-27-top10", run_dir)
        script_path = run_dir / "facts/script.json"
        script = json.loads(script_path.read_text(encoding="utf-8"))
        for record, labels in zip(script["records"], labels_by_record):
            record["content_formula"] = {"labels": labels}
            record["data_availability"]["content_formula"] = {"available": True, "missing_reason": ""}
        script_path.write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
        manifest_path = run_dir / "facts/manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["packages"]["script"]["sha256"] = hashlib.sha256(script_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        taxonomy_path = None
        if taxonomy is not None:
            taxonomy_path = Path(temp_dir.name) / "taxonomy.json"
            taxonomy_path.write_text(json.dumps(taxonomy, ensure_ascii=False), encoding="utf-8")
        return temp_dir, run_dir, taxonomy_path

    def test_top10_projects_only_explicit_taxonomy_formula_pairs(self):
        model = build_script_formula_overview(ROOT / "runs/food-drink-exposure-20260820-27-top10")
        self.assertEqual(model["status"], "available")
        self.assertEqual(model["coverage"]["formulaMaterialCount"], 2)
        self.assertEqual(
            {item["label"] for item in model["primaryBuckets"]},
            {"商品卖点", "品牌印象", "人群", "痛点", "使用场景"},
        )
        self.assertIn("功效功能", {item["label"] for item in model["secondaryBucketsByPrimary"]["商品卖点"]})
        self.assertNotIn("script_text", str(model))
        self.assertNotIn("海参", str(model))

    def test_original_run_keeps_available_empty_formula_state(self):
        model = build_script_formula_overview(ROOT / "runs/food-drink-exposure-20260820-27")
        self.assertEqual(model["status"], "available")
        self.assertEqual(model["coverage"]["formulaMaterialCount"], 0)
        self.assertEqual(model["primaryBuckets"], [])
        self.assertIn("formula_source_empty", {item["code"] for item in model["gaps"]})

    def test_explicit_source_labels_are_rendered_without_taxonomy_entry(self):
        labels = [[{"level_1_label": {"id": 99, "label": "新增一级"}, "level_2_labels": [{"id": 199, "label": "新增二级"}]}]] + [[] for _ in range(9)]
        temp_dir, run_dir, _ = self.make_script_run(labels)
        try:
            model = build_script_formula_overview(run_dir)
        finally:
            temp_dir.cleanup()
        self.assertEqual({item["label"] for item in model["primaryBuckets"]}, {"新增一级"})
        self.assertEqual({item["label"] for item in model["secondaryBucketsByPrimary"]["新增一级"]}, {"新增二级"})
        self.assertNotIn("formula_taxonomy_unmapped", {item["code"] for item in model["gaps"]})

    def test_source_label_wins_over_stale_taxonomy_and_records_conflict(self):
        labels = [[{"level_1_label": {"id": 9, "label": "接口新名称"}, "level_2_labels": []}]] + [[] for _ in range(9)]
        temp_dir, run_dir, _ = self.make_script_run(labels)
        try:
            model = build_script_formula_overview(run_dir)
        finally:
            temp_dir.cleanup()
        self.assertEqual({item["label"] for item in model["primaryBuckets"]}, {"接口新名称"})
        self.assertIn("formula_taxonomy_label_conflict", {item["code"] for item in model["gaps"]})

    def test_conflicting_explicit_names_for_one_id_are_excluded_from_aggregation(self):
        labels = [
            [{"level_1_label": {"id": 99, "label": "名称甲"}, "level_2_labels": []}],
            [{"level_1_label": {"id": 99, "label": "名称乙"}, "level_2_labels": []}],
        ] + [[] for _ in range(8)]
        temp_dir, run_dir, _ = self.make_script_run(labels)
        try:
            model = build_script_formula_overview(run_dir)
        finally:
            temp_dir.cleanup()
        self.assertEqual(model["coverage"]["formulaMaterialCount"], 0)
        self.assertEqual(model["primaryBuckets"], [])
        self.assertIn("formula_source_label_conflict", {item["code"] for item in model["gaps"]})

    def test_taxonomy_accepts_a_new_nonempty_catalog_version(self):
        payload = {"schemaVersion": 1, "version": "official-catalog-2026-10", "primary": {"9": "商品卖点"}, "secondary": {}}
        temp_dir, _, taxonomy_path = self.make_script_run([[] for _ in range(10)], payload)
        try:
            with mock.patch("scripts.script_formula_overview._TAXONOMY_PATH", taxonomy_path):
                self.assertEqual(_load_taxonomy()["version"], "official-catalog-2026-10")
        finally:
            temp_dir.cleanup()

    def test_taxonomy_rejects_invalid_schema_or_non_string_mapping(self):
        invalid = [
            {"schemaVersion": 2, "version": "x", "primary": {}, "secondary": {}},
            {"schemaVersion": 1, "version": "x", "primary": {"9": 9}, "secondary": {}},
            {"schemaVersion": 1, "version": "x", "primary": {}, "secondary": {"34": ""}},
        ]
        for payload in invalid:
            temp_dir, _, taxonomy_path = self.make_script_run([[] for _ in range(10)], payload)
            try:
                with mock.patch("scripts.script_formula_overview._TAXONOMY_PATH", taxonomy_path):
                    with self.assertRaises(ScriptFormulaOverviewError):
                        _load_taxonomy()
            finally:
                temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
