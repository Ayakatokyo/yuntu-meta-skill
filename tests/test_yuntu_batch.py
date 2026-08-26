import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
BATCH_PATH = SCRIPTS_DIR / "yuntu_batch.py"


def load_batch():
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location("yuntu_batch", BATCH_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DetailInvoker:
    def __init__(self, detail_result):
        self.detail_result = detail_result
        self.detail_calls = []

    def invoke_detail(self, shop_id, detail_params):
        self.detail_calls.append((shop_id, detail_params))
        return self.detail_result


class BatchInvoker:
    def __init__(self, list_records, failed_material_ids=()):
        self.list_records = list_records
        self.failed_material_ids = set(failed_material_ids)
        self.detail_calls = []

    def invoke_list(self, _shop_id, _list_params):
        return {"success": True, "data": self.list_records}

    def invoke_detail(self, _shop_id, detail_params):
        self.detail_calls.append(detail_params)
        material_id = detail_params["material_id"]
        if material_id in self.failed_material_ids:
            raise RuntimeError(f"detail rejected for {material_id}")
        return {
            "success": True,
            "data": [{
                "materialId": material_id,
                "dateRangeType": detail_params["date_range_type"],
                "trends": [],
                **{
                    field: detail_params[field]
                    for field in (
                        "selectionGroupId",
                        "brandId",
                        "brandName",
                        "touchpointCode",
                        "touchpointName",
                    )
                    if field in detail_params
                },
            }],
        }


def list_record(material_id, group_id):
    return {
        "material_id": material_id,
        "selectionGroupId": group_id,
        "brandId": f"brand-{group_id}",
        "brandName": f"Brand {group_id}",
    }


def highlight_spec():
    return {
        "include_cover": False,
        "metrics": {
            "点赞指数": {"strategy": "local_peaks", "limit": 1},
            "流失指数": {"strategy": "local_peaks", "limit": 1},
            "点击指数": {"strategy": "local_peaks", "limit": 1},
            "互动指数": {"strategy": "local_peaks", "limit": 1},
            "评论指数": {"strategy": "local_peaks", "limit": 1},
        },
    }


class YuntuBatchTests(unittest.TestCase):
    def test_list_context_accepts_platform_ctr_alias(self):
        batch = load_batch()
        result = batch._validate_list_context(
            [{"list_context": {"ranking_limit": "CTRTOP1000"}}],
            {"ranking_limit_type": "CTR_TOP1000"},
        )
        self.assertTrue(result["valid"])

    def test_retry_failed_batch_postprocesses_recovered_detail_and_preserves_manifest_status(self):
        batch = load_batch()
        generated_material_ids = []

        def generate_highlights(detail, _root):
            generated_material_ids.append(detail["material_id"])
            return [{
                "available": True,
                "relative_path": f"highlights/{detail['material_id']}/cover.jpg",
            }]

        batch.generate_standard_highlights_for_detail = generate_highlights
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            contract = batch.run_state.collection_contract(
                shop_id="shop-42",
                list_params={"industry": "食品饮料"},
                detail_date_params={"date_range_type": "LAST_7_DAYS"},
                target_top_n=2,
                candidate_top_n=2,
            )
            batch.run_state.save_run_state(
                batch.run_state.new_collection_summary(contract),
                root / "run-summary.json",
            )
            (root / "normalized" / "list-records.json").parent.mkdir(parents=True)
            (root / "normalized" / "list-records.json").write_text(
                json.dumps(
                    [
                        {"material_id": "101", "rank": 1},
                        {"material_id": "202", "rank": 2},
                    ]
                ),
                encoding="utf-8",
            )
            (root / "batch-manifest.json").write_text(
                json.dumps(
                    {
                        "status": "partial",
                        "detailDateRange": {"date_range_type": "LAST_7_DAYS"},
                        "targetTopN": 2,
                        "selectedMaterials": [{
                            "rank": 2,
                            "material_id": "202",
                            "postprocessStatus": "succeeded",
                        }],
                        "rejectedMaterials": [{"rank": 1, "material_id": "101"}],
                        "unresolvedMaterials": [],
                    }
                ),
                encoding="utf-8",
            )
            (root / "highlights-manifest.json").write_text(
                json.dumps(
                    {
                        "materials": [
                            {"material_id": "202", "frames": [{"relative_path": "existing.jpg"}]}
                        ]
                    }
                ),
                encoding="utf-8",
            )
            invoker = DetailInvoker(
                {
                    "success": True,
                    "data": [
                        {
                            "materialId": "101",
                            "dateRangeType": "LAST_7_DAYS",
                            "trends": [],
                        }
                    ],
                }
            )

            status = batch.retry_failed_batch(
                shop_id="shop-42", output_dir=root, invoker=invoker
            )
            manifest = json.loads((root / "batch-manifest.json").read_text(encoding="utf-8"))
            highlights = json.loads(
                (root / "highlights-manifest.json").read_text(encoding="utf-8")
            )

        recovered = next(
            item for item in manifest["selectedMaterials"] if item["material_id"] == "101"
        )
        self.assertEqual(status, 0)
        self.assertEqual(manifest["status"], "success")
        self.assertEqual(manifest["rejectedMaterials"], [])
        self.assertEqual(generated_material_ids, ["101"])
        self.assertEqual(recovered["postprocessStatus"], "succeeded")
        self.assertIn("highlightSec", recovered["postprocessTimingsSec"])
        self.assertEqual(
            {item["material_id"] for item in highlights["materials"]}, {"101", "202"}
        )

    def test_fetch_batch_requests_global_rank_top_n_across_selection_groups(self):
        batch = load_batch()
        batch.generate_highlights_for_detail = lambda *_args: []
        invoker = BatchInvoker([
            list_record("101", "A"),
            list_record("202", "B"),
            list_record("303", "A"),
        ])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status = batch.fetch_batch(
                shop_id="shop-42",
                list_params={},
                detail_date_params={"date_range_type": "LAST_7_DAYS"},
                target_top_n=2,
                candidate_top_n=1000,
                output_dir=root,
                invoker=invoker,
                highlight_spec=highlight_spec(),
            )
            manifest = json.loads((root / "batch-manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(status, 0)
        self.assertEqual([call["material_id"] for call in invoker.detail_calls], ["101", "202"])
        self.assertEqual(
            [item["material_id"] for item in manifest["candidateMaterials"]], ["101", "202"]
        )
        self.assertEqual(manifest["selectionGroups"], [])

    def test_fetch_batch_does_not_replace_failed_global_top_n_material(self):
        batch = load_batch()
        batch.generate_highlights_for_detail = lambda *_args: []
        invoker = BatchInvoker(
            [list_record("101", "A"), list_record("202", "B"), list_record("303", "A")],
            failed_material_ids={"101"},
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status = batch.fetch_batch(
                shop_id="shop-42",
                list_params={},
                detail_date_params={"date_range_type": "LAST_7_DAYS"},
                target_top_n=2,
                candidate_top_n=1000,
                output_dir=root,
                invoker=invoker,
                highlight_spec=highlight_spec(),
            )
            manifest = json.loads((root / "batch-manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(status, 1)
        self.assertEqual({call["material_id"] for call in invoker.detail_calls}, {"101", "202"})
        self.assertEqual([item["material_id"] for item in manifest["rejectedMaterials"]], ["101"])

    def test_fetch_batch_is_partial_when_a_configured_highlight_frame_is_unavailable(self):
        batch = load_batch()
        batch.generate_highlights_for_detail = lambda *_args: [{"available": False}]
        invoker = BatchInvoker([list_record("101", "A")])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status = batch.fetch_batch(
                shop_id="shop-42",
                list_params={},
                detail_date_params={"date_range_type": "LAST_7_DAYS"},
                target_top_n=1,
                candidate_top_n=1000,
                output_dir=root,
                invoker=invoker,
                highlight_spec=highlight_spec(),
            )
            manifest = json.loads((root / "batch-manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(status, 1)
        self.assertEqual(manifest["status"], "partial")
        self.assertEqual(manifest["selectedMaterials"][0]["postprocessStatus"], "failed")

    def test_fetch_batch_is_partial_when_a_highlight_has_the_wrong_second(self):
        batch = load_batch()
        batch.generate_highlights_for_detail = lambda *_args: [{
            "available": True,
            "frame_type": "custom_highlight",
            "second": 99,
            "relative_path": "highlights/101/01-099s.jpg",
        }]
        invoker = BatchInvoker([list_record("101", "A")])

        def invoke_detail(_shop_id, detail_params):
            response = BatchInvoker.invoke_detail(invoker, _shop_id, detail_params)
            response["data"][0]["trends"] = [{
                "trendName": "点击指数",
                "tendList": [
                    {"x": 0, "y": 0},
                    {"x": 1, "y": 5},
                    {"x": 2, "y": 0},
                ],
            }]
            return response

        invoker.invoke_detail = invoke_detail

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frame = root / "highlights" / "101" / "01-099s.jpg"
            frame.parent.mkdir(parents=True)
            frame.write_bytes(b"jpeg")
            status = batch.fetch_batch(
                shop_id="shop-42",
                list_params={},
                detail_date_params={"date_range_type": "LAST_7_DAYS"},
                target_top_n=1,
                candidate_top_n=1000,
                output_dir=root,
                invoker=invoker,
                highlight_spec=highlight_spec(),
            )
            manifest = json.loads((root / "batch-manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(status, 1)
        self.assertEqual(manifest["status"], "partial")
        self.assertEqual(manifest["selectedMaterials"][0]["postprocessStatus"], "failed")

    def test_retry_highlights_regenerates_only_unavailable_persisted_detail_frames(self):
        batch = load_batch()
        generated_material_ids = []

        def generate_highlights(detail, root, _highlight_spec):
            material_id = detail["material_id"]
            generated_material_ids.append(material_id)
            image = Path(root) / "highlights" / material_id / "01-001s.jpg"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"jpeg")
            return [{
                "available": True,
                "frame_type": "custom_highlight",
                "second": 1,
                "relative_path": str(image.relative_to(root)),
            }]

        batch.generate_missing_highlights_for_detail = generate_highlights
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = highlight_spec()
            contract = batch.run_state.collection_contract(
                shop_id="shop-42",
                list_params={},
                detail_date_params={"date_range_type": "LAST_7_DAYS"},
                target_top_n=1,
                candidate_top_n=1000,
            )
            batch.run_state.save_run_state(
                batch.run_state.new_collection_summary(contract),
                root / "run-summary.json",
            )
            detail_path = root / "normalized" / "detail-records" / "101.json"
            detail_path.parent.mkdir(parents=True)
            detail_path.write_text(json.dumps({
                "material_id": "101",
                "trend_series": [{
                    "trend_name": "点击指数",
                    "series": [
                        {"second": 0, "value": 0},
                        {"second": 1, "value": 5},
                        {"second": 2, "value": 0},
                    ],
                }],
            }), encoding="utf-8")
            (root / "normalized" / "list-records.json").write_text(
                json.dumps([{"material_id": "101", "rank": 1}]), encoding="utf-8"
            )
            (root / "batch-manifest.json").write_text(json.dumps({
                "status": "partial",
                "targetTopN": 1,
                "candidateMaterials": [{"rank": 1, "material_id": "101"}],
                "selectedMaterials": [{
                    "rank": 1,
                    "material_id": "101",
                    "detailRecordPath": "normalized/detail-records/101.json",
                    "postprocessStatus": "failed",
                }],
                "rejectedMaterials": [],
                "unresolvedMaterials": [],
                "cancelledMaterials": [],
            }), encoding="utf-8")

            status = batch.retry_highlights_batch(
                output_dir=root, highlight_spec=spec
            )
            manifest = json.loads((root / "batch-manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(status, 0)
        self.assertEqual(generated_material_ids, ["101"])
        self.assertEqual(manifest["status"], "success")
        self.assertEqual(manifest["selectedMaterials"][0]["postprocessStatus"], "succeeded")

    def test_scripts_package_imports_from_repository_root(self):
        result = subprocess.run(
            [sys.executable, "-c", "import scripts.yuntu_batch"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
