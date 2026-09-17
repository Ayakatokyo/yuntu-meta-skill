from pathlib import Path
import unittest

import yaml


SKILL_PATH = Path(__file__).resolve().parents[1] / "SKILL.md"
METADATA_PATH = Path(__file__).resolve().parents[1] / "metadata.yaml"


def load_skill_document():
    text = SKILL_PATH.read_text(encoding="utf-8")
    _, frontmatter, body = text.split("---\n", 2)
    return yaml.safe_load(frontmatter), body


def load_skill_form():
    return yaml.safe_load(METADATA_PATH.read_text(encoding="utf-8"))["skill_form"]


class SkillDocumentTests(unittest.TestCase):
    def test_pre_input_uses_typed_field_placeholders(self):
        metadata, _ = load_skill_document()
        pre_input = metadata["metadata"]["pre_input"]

        self.assertTrue(pre_input.startswith("请采集云图行业素材及相关数据。"))
        self.assertGreaterEqual(pre_input.count("\n"), 14)
        self.assertNotIn("<p>", pre_input)
        self.assertNotIn("data-pre-input-blank", pre_input)
        self.assertNotIn("____", pre_input)
        self.assertIn("__field:rpa_shop__", pre_input)
        self.assertIn("__field:industry__", pre_input)
        self.assertIn("__field:date_range__", pre_input)
        self.assertIn("__field:highlight_mode__", pre_input)

    def test_pre_input_keeps_query_before_highlight_rules(self):
        metadata, _ = load_skill_document()
        pre_input = metadata["metadata"]["pre_input"]

        self.assertLess(pre_input.index("行业是"), pre_input.index("是否同时生成高光帧图片"))
        self.assertIn("封面是否保留", pre_input)
        for metric in ("点赞指数", "流失指数", "点击指数", "互动指数", "评论指数"):
            self.assertIn(metric, pre_input)

    def test_pre_input_references_every_typed_form_field_once(self):
        metadata, _ = load_skill_document()
        pre_input = metadata["metadata"]["pre_input"]
        form = load_skill_form()
        keys = [field["key"] for field in form]
        references = __import__("re").findall(r"__field:([a-z0-9_]+)__", pre_input)

        self.assertEqual(keys[0], "rpa_shop")
        self.assertEqual(len(keys), 28)
        self.assertEqual(set(references), set(keys))
        self.assertEqual(len(references), len(keys))

    def test_rpa_selector_is_the_only_collection_account_field(self):
        fields = {field["key"]: field for field in load_skill_form()}

        self.assertEqual(fields["rpa_shop"]["type"], "rpa_shop")
        self.assertEqual(
            fields["rpa_shop"]["application_id"],
            "RPA_JULIANG_YT_ACCOUNT_PASSWORD",
        )
        self.assertTrue(fields["rpa_shop"]["required"])
        _, body = load_skill_document()
        self.assertIn("rpa_shop.extra.shop_id", body)
        self.assertIn("rpa_shop_not_authorized", body)

    def test_date_range_uses_the_yuntu_t_plus_4_form_policy(self):
        fields = {field["key"]: field for field in load_skill_form()}

        self.assertEqual(fields["date_range"]["max_policy"], "t_plus_4")
        self.assertIn("前 4 天", fields["date_range"]["description"])

    def test_runtime_outputs_are_kept_outside_the_skill_installation(self):
        _, body = load_skill_document()

        self.assertIn('WORKSPACE_ROOT="$PWD"', body)
        self.assertIn('$WORKSPACE_ROOT/云图数据资源/', body)
        self.assertIn("拒绝技能安装目录内的目标", body)
        self.assertIn("必须显式传 `--output-dir`", body)
        self.assertNotIn("未来运行统一写入技能根目录", body)

    def test_rpa_retry_commands_are_removed_but_local_highlight_retry_is_documented(self):
        _, body = load_skill_document()

        self.assertNotIn("retry-failed", body)
        self.assertNotIn("retry-unresolved", body)
        self.assertIn("RPA 失败项不自动重试", body)
        self.assertIn("retry-highlights", body)
        self.assertIn("不调用 RPA", body)
