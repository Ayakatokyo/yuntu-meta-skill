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
            return [{"relative_path": f"highlights/{detail['material_id']}/cover.jpg"}]

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
                        "selectedMaterials": [{"rank": 2, "material_id": "202"}],
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
