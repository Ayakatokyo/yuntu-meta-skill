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


def highlights(**overrides):
    value = {
        "schema_version": 1,
        "include_cover": True,
        "metrics": {
            "点赞指数": {"strategy": "local_peaks", "limit": 3},
            "流失指数": {"strategy": "local_peaks", "limit": 3},
            "点击指数": {"strategy": "local_peaks", "limit": 3},
            "互动指数": {"strategy": "local_peaks", "limit": 3},
            "评论指数": {"strategy": "local_peaks", "limit": 3},
        },
    }
    value.update(overrides)
    return value


class ConfigSpecTests(unittest.TestCase):
    def test_query_uses_fixed_top_1000_list_capacity_and_translates_rpa_parameters(self):
        resolved = resolve_query_spec(query())
        self.assertEqual(resolved["collection"], {"target_top_n": 10, "candidate_top_n": 1000})
        self.assertEqual(query_to_rpa_params(resolved)["ranking_limit_type"], "CTR_TOP1000")
        self.assertEqual(detail_to_rpa_params(resolved), {"date_range_type": "LAST_7_DAYS"})
        with self.assertRaisesRegex(ConfigSpecError, "must be 1000"):
            resolve_query_spec(query(collection={"target_top_n": 2, "candidate_top_n": 4}))
        with self.assertRaisesRegex(ConfigSpecError, "cannot exceed 1000"):
            resolve_query_spec(query(collection={"target_top_n": 1001}))

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

    def test_highlight_requires_explicit_cover_and_all_metrics(self):
        resolved = resolve_highlight_spec(highlights(
            metrics={
                **highlights()["metrics"],
                "点击指数": {"strategy": "absolute_max", "limit": 1},
            },
        ))
        self.assertTrue(resolved["include_cover"])
        self.assertEqual(resolved["metrics"]["点击指数"], {"strategy": "absolute_max", "limit": 1})
        self.assertEqual(set(resolved["metrics"]), {"点赞指数", "流失指数", "点击指数", "互动指数", "评论指数"})
        with self.assertRaisesRegex(ConfigSpecError, "include_cover"):
            resolve_highlight_spec({"metrics": highlights()["metrics"]})
        with self.assertRaisesRegex(ConfigSpecError, "all five metrics"):
            resolve_highlight_spec({
                "include_cover": True,
                "metrics": {"点击指数": {"strategy": "local_peaks", "limit": 1}},
            })

    def test_highlight_rejects_unknown_strategy_and_nonpositive_limit(self):
        invalid_strategy = highlights(
            metrics={
                **highlights()["metrics"],
                "点击指数": {"strategy": "median", "limit": 1},
            },
        )
        with self.assertRaisesRegex(ConfigSpecError, "unsupported"):
            resolve_highlight_spec(invalid_strategy)
        invalid_limit = highlights(
            metrics={
                **highlights()["metrics"],
                "点击指数": {"strategy": "local_peaks", "limit": 0},
            },
        )
        with self.assertRaisesRegex(ConfigSpecError, "positive"):
            resolve_highlight_spec(invalid_limit)

    def test_fingerprint_and_atomic_resolved_files_are_stable(self):
        resolved_query = resolve_query_spec(query())
        resolved_highlights = resolve_highlight_spec(highlights())
        self.assertEqual(spec_fingerprint(resolved_query, resolved_highlights), spec_fingerprint(resolved_query, resolved_highlights))
        with tempfile.TemporaryDirectory() as directory:
            query_path, highlight_path = write_resolved_specs(directory, resolved_query, resolved_highlights)
            self.assertEqual(json.loads(Path(query_path).read_text()), resolved_query)
            self.assertEqual(json.loads(Path(highlight_path).read_text()), resolved_highlights)


if __name__ == "__main__":
    unittest.main()
