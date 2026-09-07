import unittest
from pathlib import Path

from scripts.material_field_registry import MaterialFieldRegistry
from scripts.material_list_selection import (
    MaterialListSelectionError,
    select_materials,
)


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = MaterialFieldRegistry.from_path(
    ROOT / "config" / "yuntu-material-field-registry-v1.json"
)


RECORDS = [
    {
        "material_id": "1", "rank": 1, "title": "普通燕窝", "metrics": {
            "show_cnt": 100, "interact_rate": 0.10,
        }, "people_tags": ["精致妈妈"], "material_tags": ["口播"],
    },
    {
        "material_id": "2", "rank": 2, "title": "不匹配", "metrics": {
            "show_cnt": 200, "interact_rate": 0.20,
        }, "people_tags": ["小镇青年"], "material_tags": [],
    },
    {
        "material_id": "3", "rank": 3, "title": "高互动燕窝", "metrics": {
            "show_cnt": 300, "interact_rate": 0.30,
        }, "people_tags": ["精致妈妈"], "material_tags": ["情景剧"],
    },
    {
        "material_id": "4", "rank": 4, "title": "缺少互动率", "metrics": {
            "show_cnt": 400,
        }, "people_tags": ["精致妈妈"], "material_tags": [],
    },
]


class MaterialListSelectionTests(unittest.TestCase):
    def test_select_materials_applies_all_filters_then_descending_metric_sort(self):
        selected = select_materials(RECORDS, {
            "filters": [
                {"field": "metrics.show_cnt", "operator": "gte", "value": 100},
                {"field": "title", "operator": "contains", "value": "燕窝"},
            ],
            "sort": {"field": "metrics.interact_rate", "direction": "desc"},
        }, REGISTRY)

        self.assertEqual([item["material_id"] for item in selected], ["3", "1"])

    def test_select_materials_keeps_missing_sort_values_last_and_rank_id_stable(self):
        selected = select_materials(RECORDS, {
            "filters": [], "sort": {"field": "metrics.interact_rate", "direction": "asc"}
        }, REGISTRY)

        self.assertEqual([item["material_id"] for item in selected], ["1", "2", "3", "4"])

    def test_select_materials_matches_any_tag_for_contains(self):
        selected = select_materials(RECORDS, {
            "filters": [{"field": "people_tags", "operator": "contains", "value": "妈妈"}],
            "sort": {"field": "rank", "direction": "asc"},
        }, REGISTRY)

        self.assertEqual([item["material_id"] for item in selected], ["1", "3", "4"])

    def test_select_materials_returns_empty_without_inventing_fallback(self):
        selected = select_materials(RECORDS, {
            "filters": [{"field": "title", "operator": "contains", "value": "不存在"}],
            "sort": {"field": "rank", "direction": "asc"},
        }, REGISTRY)

        self.assertEqual(selected, [])

    def test_select_materials_rejects_malformed_spec_outside_config_parser(self):
        with self.assertRaises(MaterialListSelectionError):
            select_materials(
                RECORDS,
                {"filters": [], "sort": {"field": "ROI", "direction": "asc"}},
                REGISTRY,
            )


if __name__ == "__main__":
    unittest.main()
