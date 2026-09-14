from pathlib import Path
import unittest

import yaml


SKILL_PATH = Path(__file__).resolve().parents[1] / "SKILL.md"


def load_skill_document():
    text = SKILL_PATH.read_text(encoding="utf-8")
    _, frontmatter, body = text.split("---\n", 2)
    return yaml.safe_load(frontmatter), body


class SkillDocumentTests(unittest.TestCase):
    def test_pre_input_uses_platform_html_blocks_and_blank_spans(self):
        metadata, _ = load_skill_document()
        pre_input = metadata["metadata"]["pre_input"]

        self.assertTrue(pre_input.startswith("请采集云图行业素材及相关数据。"))
        self.assertGreaterEqual(pre_input.count("\n"), 14)
        self.assertNotIn("<p>", pre_input)
        self.assertNotIn("data-pre-input-blank", pre_input)
        self.assertIn("____", pre_input)

    def test_pre_input_keeps_query_before_highlight_rules(self):
        metadata, _ = load_skill_document()
        pre_input = metadata["metadata"]["pre_input"]

        self.assertLess(pre_input.index("行业是"), pre_input.index("是否同时生成高光帧图片"))
        self.assertLess(pre_input.index("是否同时生成高光帧图片"), pre_input.index("高光帧设置"))
        for metric in ("点赞指数", "流失指数", "点击指数", "互动指数", "评论指数"):
            self.assertIn(metric, pre_input)
