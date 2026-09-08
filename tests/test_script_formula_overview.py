import unittest
from pathlib import Path

from scripts.script_formula_overview import build_script_formula_overview


ROOT = Path(__file__).resolve().parents[1]


class ScriptFormulaOverviewTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
