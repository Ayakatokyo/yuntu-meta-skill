import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "yuntu_normalizer.py"


def load_module():
    spec = importlib.util.spec_from_file_location("yuntu_normalizer", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class YuntuNormalizerTests(unittest.TestCase):
    def test_normalize_list_records_preserves_material_identity_and_business_date(self):
        normalizer = load_module()
        record = normalizer.normalize_list_records(
            [{
                "material_id": "101",
                "item_id": "item-1",
                "object_type": "video",
                "bizDate": "2026-07-01",
                "material_uri": "aweme://101",
                "accountId": "shop-1",
                "page_industry": "食品饮料",
            }],
            source_path="raw-csv/list.csv",
        )[0]

        self.assertEqual(record["item_id"], "item-1")
        self.assertEqual(record["object_type"], "video")
        self.assertEqual(record["business_date"], "2026-07-01")
        self.assertEqual(record["material_uri"], "aweme://101")
        self.assertEqual(record["account_id"], "shop-1")
        self.assertEqual(record["list_context"]["industry"], "食品饮料")

    def test_normalize_list_records_extracts_metrics_tags_and_rank(self):
        normalizer = load_module()
        raw = [
            {
                "title": "洽洽你也太卷了，这价拿到这么大一箱！#洽洽",
                "material_id": "7620993598538301494",
                "video_duration": "31",
                "object_index": {
                    "ctr": 0.664652568,
                    "show_cnt": "1655",
                    "cvr": 0.1709090909,
                    "pvr": 0.1135951662,
                    "play_over_rate": 0.239633818,
                    "play_duration_avg": 13.752265861,
                    "publish_time": "20260325",
                },
                "people_tag_entry": [
                    {
                        "people_tag_type": 4,
                        "tag_name_list": ["都市银发", "小镇中老年"],
                    },
                    {"people_tag_type": 3, "tag_name_list": ["60+", "51-55"]},
                ],
                "material_tag_entry": [
                    {
                        "material_tag_type": 52,
                        "tag_name_list": [
                            "包装_独立包装",
                            "使用感受和服务体验_便携",
                        ],
                    },
                    {"material_tag_type": 58, "tag_name_list": ["使用场景_健身"]},
                ],
            }
        ]

        records = normalizer.normalize_list_records(
            raw, source_path="raw-csv/list.csv"
        )

        self.assertEqual(records[0]["material_id"], "7620993598538301494")
        self.assertEqual(records[0]["rank"], 1)
        self.assertEqual(records[0]["metrics"]["ctr"], 0.664652568)
        self.assertEqual(records[0]["metrics"]["show_cnt"], 1655)
        self.assertEqual(
            records[0]["people_tags"], ["都市银发", "小镇中老年", "60+", "51-55"]
        )
        self.assertIn("包装_独立包装", records[0]["material_tags"])
        self.assertEqual(records[0]["source_paths"]["list"], "raw-csv/list.csv")
        self.assertEqual(
            records[0]["data_availability"],
            {
                "metrics": {"available": True, "missing_reason": ""},
                "people_tags": {"available": True, "missing_reason": ""},
                "material_tags": {"available": True, "missing_reason": ""},
            },
        )

    def test_normalize_list_records_preserves_requested_top1000_metrics_only(self):
        normalizer = load_module()
        record = normalizer.normalize_list_records(
            [{
                "material_id": "101",
                "object_index": {
                    "show_cnt": "1000",
                    "ctr": 0.1,
                    "cvr": 0.2,
                    "play_3s_rate": 0.3,
                    "interact_cnt": "9",
                    "like_rate": 0.01,
                },
            }],
            source_path="raw-csv/list.csv",
        )[0]

        self.assertEqual(
            record["metrics"],
            {"show_cnt": 1000, "ctr": 0.1, "cvr": 0.2, "play_3s_rate": 0.3},
        )

    def test_normalize_list_records_marks_unparsed_nested_values_unavailable(self):
        normalizer = load_module()

        record = normalizer.normalize_list_records(
            [
                {
                    "material_id": "101",
                    "object_index": "{'ctr': invalid}",
                    "people_tag_entry": "[bad]",
                    "material_tag_entry": "[bad]",
                }
            ],
            source_path="raw-csv/list.csv",
        )[0]

        self.assertEqual(record["metrics"], {})
        self.assertEqual(record["people_tags"], [])
        self.assertEqual(record["material_tags"], [])
        self.assertEqual(
            record["data_availability"]["metrics"]["missing_reason"],
            "unparsed_source_value",
        )
        self.assertEqual(
            record["data_availability"]["people_tags"]["missing_reason"],
            "unparsed_source_value",
        )
        self.assertEqual(
            record["data_availability"]["material_tags"]["missing_reason"],
            "unparsed_source_value",
        )

    def test_normalize_list_records_rejects_missing_numeric_material_id(self):
        normalizer = load_module()
        with self.assertRaisesRegex(normalizer.YuntuNormalizeError, "material_id"):
            normalizer.normalize_list_records(
                [{"material_id": "abc"}], source_path="raw-csv/list.csv"
            )

    def test_normalize_detail_records_extracts_trends(self):
        normalizer = load_module()
        raw = [
            {
                "materialId": "7648216411198554162",
                "startDate": "2026-06-23",
                "endDate": "2026-06-29",
                "dateRangeType": "LAST_7_DAYS",
                "videoUrl": "https://video.example/material.mp4",
                "trends": [
                    {
                        "trendName": "点击指数",
                        "trendType": 3,
                        "tendList": [{"x": 0, "y": 0.5}, {"x": 1, "y": 1}],
                        "highPoint": {"start_point": "1", "end_point": "2"},
                        "lossPoint": {
                            "start_point": "0",
                            "end_point": "1",
                            "loss_percent": 0.5,
                        },
                    }
                ],
            }
        ]

        record = normalizer.normalize_detail_records(
            raw,
            material_id="7648216411198554162",
            source_path="raw-csv/details/7648216411198554162.csv",
        )

        self.assertEqual(record["material_id"], "7648216411198554162")
        self.assertEqual(record["date_range"]["type"], "LAST_7_DAYS")
        self.assertEqual(record["trend_series"][0]["trend_name"], "点击指数")
        self.assertEqual(record["high_points"][0]["start_sec"], 1)
        self.assertEqual(record["loss_points"][0]["loss_percent"], 0.5)
        self.assertEqual(
            record["data_availability"]["trends"],
            {"available": True, "missing_reason": ""},
        )
        self.assertTrue(record["data_availability"]["high_points"]["available"])
        self.assertTrue(record["data_availability"]["loss_points"]["available"])

    def test_normalize_detail_records_marks_unparsed_trends_unavailable(self):
        normalizer = load_module()

        record = normalizer.normalize_detail_records(
            [{"materialId": "101", "trends": "not a list"}],
            material_id="101",
            source_path="raw-csv/details/101.csv",
        )

        self.assertEqual(record["trend_series"], [])
        self.assertEqual(
            record["data_availability"]["trends"]["missing_reason"],
            "unparsed_source_value",
        )

    def test_normalize_detail_records_keeps_rpa_script_contract_and_group_echo(self):
        normalizer = load_module()
        expected_group = {
            "id": "brand-a:feed",
            "brand_id": "brand-a",
            "brand_name": "品牌 A",
            "touchpoint_code": "feed",
            "touchpoint_name": "信息流",
        }

        record = normalizer.normalize_detail_records(
            {
                "materialId": "101",
                "selectionGroupId": "brand-a:feed",
                "brandId": "brand-a",
                "brandName": "品牌 A",
                "touchpointCode": "feed",
                "touchpointName": "信息流",
                "scriptText": "前 3 秒提出肠胃痛点。",
                "contentFormula": {"hook": "痛点", "proof": "成分"},
                "scriptSegments": [
                    {"startMs": 0, "endMs": 3000, "text": "肠胃总不舒服？"}
                ],
                "trends": [],
            },
            material_id="101",
            source_path="raw-json/details/101.json",
            expected_selection_group=expected_group,
        )

        self.assertEqual(record["selection_group"], expected_group)
        self.assertEqual(record["script_text"], "前 3 秒提出肠胃痛点。")
        self.assertEqual(record["content_formula"]["hook"], "痛点")
        self.assertEqual(
            record["script_segments"],
            [{"start_ms": 0, "end_ms": 3000, "text": "肠胃总不舒服？"}],
        )
        self.assertTrue(record["data_availability"]["script_segments"]["available"])


if __name__ == "__main__":
    unittest.main()
