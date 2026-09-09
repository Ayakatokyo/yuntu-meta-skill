import json
import tempfile
import unittest
from pathlib import Path

from scripts.material_field_registry import (
    MaterialFieldRegistry,
    MaterialFieldRegistryError,
)


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "yuntu-material-field-registry-v1.json"


class MaterialFieldRegistryTests(unittest.TestCase):
    def test_registry_resolves_verified_label_alias_and_english_id(self):
        registry = MaterialFieldRegistry.from_path(REGISTRY)

        self.assertEqual(registry.resolve("曝光量").id, "metrics.show_cnt")
        self.assertEqual(registry.resolve("  3S完播率 ").id, "metrics.play_3s_rate")
        self.assertEqual(registry.resolve("3S 完播率").id, "metrics.play_3s_rate")
        self.assertEqual(registry.resolve("metrics.ctr").label, "CTR（点击率）")

    def test_registry_exposes_detail_rate_metrics_without_component_click_rate(self):
        registry = MaterialFieldRegistry.from_path(REGISTRY)

        self.assertEqual(registry.resolve("点赞率").id, "metrics.like_rate")
        self.assertEqual(registry.resolve("评论率").id, "metrics.comment_rate")
        self.assertEqual(registry.resolve("转发率").id, "metrics.share_rate")
        self.assertEqual(registry.resolve("商品收藏加购率").id, "metrics.product_wish_button_buy_cart_rate")
        with self.assertRaisesRegex(MaterialFieldRegistryError, "unknown"):
            registry.resolve("组件点击率")

    def test_registry_reads_only_declared_record_paths(self):
        registry = MaterialFieldRegistry.from_path(REGISTRY)
        record = {"metrics": {"show_cnt": 123}, "title": "燕窝"}

        self.assertEqual(registry.value(record, "metrics.show_cnt"), 123)
        self.assertIsNone(registry.value(record, "metrics.interact_rate"))

    def test_registry_rejects_duplicate_normalized_label_and_undeclared_path(self):
        payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
        payload["fields"].append({
            "id": "duplicate.field",
            "label": "  曝光量 ",
            "kind": "number",
            "path": ["metrics", "show_cnt"],
            "filterOperators": ["eq"],
            "sortable": True,
            "labelEvidence": "test",
        })
        with tempfile.TemporaryDirectory() as directory:
            duplicate_path = Path(directory) / "duplicate.json"
            duplicate_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(MaterialFieldRegistryError, "duplicate"):
                MaterialFieldRegistry.from_path(duplicate_path)

    def test_registry_rejects_unknown_field(self):
        registry = MaterialFieldRegistry.from_path(REGISTRY)

        with self.assertRaisesRegex(MaterialFieldRegistryError, "unknown"):
            registry.resolve("ROI")


if __name__ == "__main__":
    unittest.main()
