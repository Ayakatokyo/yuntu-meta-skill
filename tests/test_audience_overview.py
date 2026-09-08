import unittest
from pathlib import Path

from scripts.audience_overview import build_audience_overview


ROOT = Path(__file__).resolve().parents[1]


class AudienceOverviewTests(unittest.TestCase):
    def test_real_runs_only_expose_material_coverage_buckets(self):
        model = build_audience_overview(ROOT / "runs/food-drink-exposure-20260820-27")
        self.assertEqual(model["status"], "available")
        self.assertEqual(model["materialScope"]["count"], 1000)
        self.assertEqual(model["metric"]["id"], "MATERIAL_COVERAGE")
        self.assertEqual(len(model["dimensions"]["crowd_group"]["buckets"]), 8)
        self.assertEqual(model["dimensions"]["crowd_group"]["chart"], "bar")
        self.assertEqual(model["dimensions"]["gender"]["chart"], "donut")
        self.assertEqual(model["dimensions"]["age"]["chart"], "donut")
        self.assertNotIn("show_cnt", str(model))
        self.assertNotIn("script_text", str(model))


if __name__ == "__main__":
    unittest.main()
