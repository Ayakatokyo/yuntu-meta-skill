from pathlib import Path
import unittest

import yaml


SKILL_PATH = Path(__file__).resolve().parents[1] / "SKILL.md"
METADATA_PATH = Path(__file__).resolve().parents[1] / "metadata.yaml"


def load_skill_document():
    text = SKILL_PATH.read_text(encoding="utf-8")
    _, frontmatter, body = text.split("---\n", 2)
    return yaml.safe_load(frontmatter), body


def load_skill_metadata():
    frontmatter, _ = load_skill_document()
    sidecar = yaml.safe_load(METADATA_PATH.read_text(encoding="utf-8"))
    return {**frontmatter.get("metadata", {}), **sidecar}


def load_skill_form():
    return load_skill_metadata()["skill_form"]


class SkillDocumentTests(unittest.TestCase):
    def test_derived_skill_keeps_runtime_date_policy(self):
        _, body = load_skill_document()
        self.assertIn("## 从完整运行创建新 Skill", body)
        self.assertIn("scripts/date_policy.py", body)
        self.assertIn("非法日期不会提交任何 RPA", body)

    def test_pre_input_uses_typed_field_placeholders(self):
        pre_input = load_skill_metadata()["pre_input"]

        self.assertTrue(pre_input.startswith("请采集云图行业素材及相关数据。"))
        self.assertGreaterEqual(pre_input.count("\n"), 11)
        self.assertNotIn("<p>", pre_input)
        self.assertNotIn("data-pre-input-blank", pre_input)
        self.assertNotIn("____", pre_input)
        self.assertIn("__field:rpa_shop__", pre_input)
        self.assertIn("__field:industry__", pre_input)
        self.assertIn("__field:date_range__", pre_input)
        self.assertIn("__field:highlight_mode__", pre_input)
        self.assertIn("__field:highlight_rules__", pre_input)
        self.assertIn("可用指标：点赞指数、流失指数、点击指数、互动指数、评论指数", pre_input)
        self.assertIn("不保留封面，提取点赞指数局部峰值3帧、互动指数最高值2帧", pre_input)

    def test_pre_input_keeps_query_before_highlight_rules(self):
        pre_input = load_skill_metadata()["pre_input"]

        self.assertLess(pre_input.index("行业是"), pre_input.index("是否同时生成高光帧图片"))
        self.assertIn("高光帧规则", pre_input)
        for metric in ("点赞指数", "流失指数", "点击指数", "互动指数", "评论指数"):
            self.assertIn(metric, pre_input)
        self.assertNotIn("highlight_include_cover", pre_input)
        self.assertNotIn("highlight_like_enabled", pre_input)

    def test_pre_input_references_every_typed_form_field_once(self):
        pre_input = load_skill_metadata()["pre_input"]
        form = load_skill_form()
        keys = [field["key"] for field in form]
        references = __import__("re").findall(r"__field:([a-z0-9_]+)__", pre_input)

        self.assertEqual(keys[0], "rpa_shop")
        self.assertEqual(len(keys), 13)
        self.assertEqual(set(references), set(keys))
        self.assertEqual(len(references), len(keys))

    def test_highlight_rules_is_a_conditional_textarea(self):
        fields = {field["key"]: field for field in load_skill_form()}

        self.assertEqual(fields["highlight_rules"]["type"], "textarea")
        self.assertTrue(fields["highlight_rules"]["required"])
        self.assertEqual(fields["highlight_rules"]["visible_when"], {"field": "highlight_mode", "equals": "on"})
        self.assertEqual(fields["highlight_rules"]["depends_on"], {"highlight_mode": "on"})
        self.assertIn("封面", fields["highlight_rules"]["description"])
        self.assertIn("点赞指数", fields["highlight_rules"]["placeholder"])

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
