import json
import tempfile
import unittest
from pathlib import Path

from scripts.config_specs import resolve_highlight_request, resolve_query_spec
from scripts.yuntu_batch import fetch_batch


QUERY = {
    "schema_version": 1,
    "source": "juliang_yuntu_industry_content_rankings",
    "industry": "食品饮料",
    "period": {"type": "LAST_7_DAYS"},
    "ranking": {"metric": "CTR_TOP1000"},
}


class _Invoker:
    def invoke_list(self, _shop_id, _params):
        return {"success": True, "data": [{"materialId": "101"}]}

    def invoke_detail(self, _shop_id, params):
        return {"success": True, "data": [{
            "materialId": params["material_id"],
            "dateRangeType": params["date_range_type"],
            "trends": [{"trendName": "点击指数", "series": [{"second": 0, "value": 1}]}],
        }]}


class OptionalHighlightTests(unittest.TestCase):
    def test_omitted_highlight_request_defaults_to_off_without_a_spec(self):
        request = resolve_highlight_request(None)

        self.assertEqual(request, {
            "enabled": False,
            "spec": None,
            "request_source": "default_off",
        })

    def test_explicitly_disabled_highlights_reject_a_rule(self):
        with self.assertRaisesRegex(ValueError, "highlight_request_conflict"):
            resolve_highlight_request({"include_cover": True, "metrics": {"点赞指数": {"strategy": "local_peaks", "limit": 1}}}, enabled=False)

    def test_collection_without_highlights_never_calls_the_frame_generator(self):
        query = resolve_query_spec(QUERY)
        with tempfile.TemporaryDirectory() as directory:
            result = fetch_batch(
                shop_id="shop-1",
                list_params={},
                detail_date_params={"date_range_type": "LAST_7_DAYS"},
                target_top_n=1,
                candidate_top_n=1000,
                output_dir=Path(directory),
                invoker=_Invoker(),
                highlight_spec=None,
            )
            manifest = json.loads((Path(directory) / "batch-manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(query["collection"]["target_top_n"], 10)
        self.assertEqual(result, 0)
        self.assertEqual(manifest["status"], "success")
        self.assertEqual(manifest["selectedMaterials"][0]["postprocessStatus"], "not_requested")
