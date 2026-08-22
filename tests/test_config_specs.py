import json
import tempfile
import unittest
from pathlib import Path

from scripts.config_specs import (
    ConfigSpecError,
    detail_to_rpa_params,
    query_to_rpa_params,
    resolve_highlight_spec,
    resolve_query_spec,
    spec_fingerprint,
    write_resolved_specs,
)


def query(**overrides):
    value = {
        "schema_version": 1,
        "source": "juliang_yuntu_industry_content_rankings",
        "industry": "食品饮料",
        "period": {"type": "LAST_7_DAYS"},
        "ranking": {"metric": "CTR_TOP1000"},
    }
    value.update(overrides)
    return value


class ConfigSpecTests(unittest.TestCase):
    def test_query_defaults_and_rpa_translation(self):
        resolved = resolve_query_spec(query())
        self.assertEqual(resolved["collection"], {"target_top_n": 10, "candidate_top_n": 20})
        self.assertEqual(query_to_rpa_params(resolved)["ranking_limit_type"], "CTR_TOP1000")
        self.assertEqual(detail_to_rpa_params(resolved), {"date_range_type": "LAST_7_DAYS"})

    def test_query_rejects_unknown_fields_and_invalid_brand_scope(self):
        with self.assertRaisesRegex(ConfigSpecError, "unknown QuerySpec fields"):
            resolve_query_spec(query(extra=True))
        with self.assertRaisesRegex(ConfigSpecError, "3 to 10"):
            resolve_query_spec(query(filters={"brand_scope": {"type": "SPECIFIED_BRANDS", "brands": []}}))

    def test_custom_period_and_filters_are_preserved(self):
        resolved = resolve_query_spec(query(
            period={"type": "CUSTOM", "start_date": "20260801", "end_date": "20260805"},
            filters={
                "ages": ["AGE_24_30"],
                "genders": ["FEMALE"],
                "crowd_groups": ["REFINED_MOM"],
                "brand_scope": {"type": "SPECIFIED_BRANDS", "brands": ["甲", "乙", "丙"]},
            },
        ))
        self.assertEqual(query_to_rpa_params(resolved)["brands"], ["甲", "乙", "丙"])
        self.assertEqual(detail_to_rpa_params(resolved)["custom_end_date"], "20260805")

    def test_highlight_defaults_and_independent_strategies(self):
        resolved = resolve_highlight_spec({
            "schema_version": 1,
            "metrics": {"点击指数": {"strategy": "absolute_max", "limit": 1}},
        })
        self.assertTrue(resolved["include_cover"])
        self.assertEqual(resolved["metrics"]["点击指数"], {"strategy": "absolute_max", "limit": 1})
        self.assertEqual(set(resolved["metrics"]), {"点赞指数", "流失指数", "点击指数", "互动指数", "评论指数"})

    def test_highlight_rejects_unknown_strategy_and_nonpositive_limit(self):
        with self.assertRaisesRegex(ConfigSpecError, "unsupported"):
            resolve_highlight_spec({"metrics": {"点击指数": {"strategy": "median"}}})
        with self.assertRaisesRegex(ConfigSpecError, "positive"):
            resolve_highlight_spec({"metrics": {"点击指数": {"limit": 0}}})

    def test_fingerprint_and_atomic_resolved_files_are_stable(self):
        resolved_query = resolve_query_spec(query())
        resolved_highlights = resolve_highlight_spec({})
        self.assertEqual(spec_fingerprint(resolved_query, resolved_highlights), spec_fingerprint(resolved_query, resolved_highlights))
        with tempfile.TemporaryDirectory() as directory:
            query_path, highlight_path = write_resolved_specs(directory, resolved_query, resolved_highlights)
            self.assertEqual(json.loads(Path(query_path).read_text()), resolved_query)
            self.assertEqual(json.loads(Path(highlight_path).read_text()), resolved_highlights)


if __name__ == "__main__":
    unittest.main()
