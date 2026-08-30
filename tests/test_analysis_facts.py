import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts.analysis_facts import build_fact_index, load_selected_facts
from scripts.analysis_spec import parse_analysis_spec


class AnalysisFactsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "facts").mkdir()
        self.manifest = {
            "schema_version": 1,
            "run_id": "run-1",
            "packages": {
                "material_ranking": {"path": "facts/material-ranking.json", "record_count": 1},
                "audience": {"path": "facts/audience.json", "record_count": 1},
                "script": {"path": "facts/script.json", "record_count": 1},
                "highlight_frames": {"path": "facts/highlight-frames.json", "record_count": 1},
            },
            "source_artifacts": [],
        }
        (self.root / "facts/manifest.json").write_text(
            json.dumps(self.manifest), encoding="utf-8"
        )
        self._write_package("material-ranking.json", [{"material_id": "101", "rank": 1}])
        self._write_package("audience.json", [{"material_id": "101", "rank": 1}])
        self._write_package("script.json", [{
            "material_id": "101",
            "data_availability": {
                "script_text": {"available": False, "missing_reason": "source_empty"}
            },
        }])
        self._write_package("highlight-frames.json", [{"material_id": "101", "frames": []}])

    def tearDown(self):
        self.temp.cleanup()

    def _write_package(self, filename, records):
        (self.root / "facts" / filename).write_text(
            json.dumps({"schema_version": 1, "records": records}), encoding="utf-8"
        )

    def _spec(self, sections, rank_range=(1, 1)):
        return parse_analysis_spec({
            "analysis_id": "analysis-1", "run_id": "run-1", "sections": sections,
            "business_question": "比较素材表现", "filters": {"rank_range": list(rank_range)},
        })

    def test_single_module_loads_only_that_package(self):
        selected = load_selected_facts(self.root, self._spec(["material_ranking"]))
        self.assertEqual(set(selected["sections"]), {"material_ranking"})
        self.assertEqual(selected["sections"]["material_ranking"]["record_count"], 1)
        self.assertNotIn("audience", selected["sections"])

    def test_multi_module_load_preserves_paths_and_source_empty(self):
        selected = load_selected_facts(self.root, self._spec(["audience", "script"]))
        script = selected["sections"]["script"]
        self.assertEqual(script["path"], "facts/script.json")
        self.assertEqual(script["records"][0]["data_availability"]["script_text"]["missing_reason"], "source_empty")

    def test_fact_refs_resolve_to_actual_records(self):
        selected = load_selected_facts(self.root, self._spec(["material_ranking", "audience"]))
        index = build_fact_index(selected)
        self.assertEqual(index["facts/material-ranking.json#/records/0"]["material_id"], "101")
        self.assertEqual(index["facts/audience.json#/records/0"]["material_id"], "101")

    def test_fact_refs_keep_original_package_index_after_rank_filter(self):
        self.manifest["packages"]["material_ranking"]["record_count"] = 2
        self._write_package("material-ranking.json", [
            {"material_id": "100", "rank": 1}, {"material_id": "101", "rank": 2},
        ])
        (self.root / "facts/manifest.json").write_text(
            json.dumps(self.manifest), encoding="utf-8"
        )
        selected = load_selected_facts(self.root, self._spec(["material_ranking"], rank_range=(2, 2)))
        self.assertEqual(selected["sections"]["material_ranking"]["record_indices"], [1])
        index = build_fact_index(selected)
        self.assertNotIn("facts/material-ranking.json#/records/0", index)
        self.assertEqual(index["facts/material-ranking.json#/records/1"]["material_id"], "101")

    def test_declared_package_hash_rejects_tampering(self):
        package_path = self.root / "facts/material-ranking.json"
        expected = hashlib.sha256(package_path.read_bytes()).hexdigest()
        self.manifest["packages"]["material_ranking"]["sha256"] = expected
        (self.root / "facts/manifest.json").write_text(
            json.dumps(self.manifest), encoding="utf-8"
        )
        package_path.write_text(package_path.read_text() + " ", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            load_selected_facts(self.root, self._spec(["material_ranking"]))


if __name__ == "__main__":
    unittest.main()
