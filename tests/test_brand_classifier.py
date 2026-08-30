import unittest

from scripts.brand_classifier import build_brand_rules, classify_brand


class BrandClassifierTests(unittest.TestCase):
    def test_runtime_rules_split_slash_and_keep_order(self):
        rules = build_brand_rules(["Brand A / 品牌A", "燕之屋", "Brand A / 品牌A"])

        self.assertEqual([rule.canonical for rule in rules], ["Brand A / 品牌A", "燕之屋"])
        self.assertEqual(rules[0].tokens, ("Brand A", "品牌A"))

    def test_nfkc_casefold_and_continuous_tokens(self):
        result = classify_brand("新品ＡＢＣabc品牌A连续出现", brands=["ABC", "品牌A"])

        self.assertEqual(result["value"], ["ABC", "品牌A"])
        self.assertEqual(result["matchedBrands"], ["ABC", "品牌A"])
        self.assertEqual(result["source"], "runtime_title_rule")
        self.assertEqual(result["match_tokens"], {"ABC": ["ABC"], "品牌A": ["品牌A"]})

    def test_multiple_brands_are_all_retained_for_a_single_title(self):
        result = classify_brand("品牌A与Brand B联合内容", brands=["品牌A", "Brand B"])

        self.assertEqual(result["value"], ["品牌A", "Brand B"])
        self.assertEqual(result["matchedBrands"], ["品牌A", "Brand B"])
        self.assertEqual(result["match_tokens"], {
            "品牌A": ["品牌A"],
            "Brand B": ["Brand B"],
        })

    def test_single_brand_keeps_scalar_value_and_audit_evidence(self):
        result = classify_brand("这是品牌A的产品", brands=["品牌A"])

        self.assertEqual(result, {
            "value": "品牌A",
            "matchedBrands": ["品牌A"],
            "source": "runtime_title_rule",
            "match_tokens": {"品牌A": ["品牌A"]},
        })

    def test_unknown_and_empty_runtime_scope_never_use_default_brands(self):
        for brands in ([], None, ["小仙炖"]):
            with self.subTest(brands=brands):
                result = classify_brand("万益蓝 Wonderlab", brands=brands)
                self.assertEqual(result["value"], "未知品牌")
                self.assertEqual(result["matchedBrands"], [])
                self.assertEqual(result["source"], "unclassified")
                self.assertEqual(result["match_tokens"], {})

    def test_jiuyang_soymilk_has_explicit_controlled_variant_only(self):
        matched = classify_brand("九阳自律豆浆新品", brands=["九阳豆浆"])
        direct = classify_brand("九阳豆浆新品", brands=["九阳豆浆"])
        standalone = classify_brand("九阳新品", brands=["九阳豆浆"])

        self.assertEqual(matched["value"], "九阳豆浆")
        self.assertEqual(matched["matchedBrands"], ["九阳豆浆"])
        self.assertEqual(matched["match_tokens"], {"九阳豆浆": ["九阳自律豆浆"]})
        self.assertEqual(direct["match_tokens"], {"九阳豆浆": ["九阳豆浆"]})
        self.assertEqual(standalone["value"], "未知品牌")


if __name__ == "__main__":
    unittest.main()
