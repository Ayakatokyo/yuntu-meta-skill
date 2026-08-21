import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "rpa_io.py"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "yuntu_rpa_export_sample.csv"


def load_module():
    spec = importlib.util.spec_from_file_location("rpa_io", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeDownloadResponse:
    def __init__(self, chunks, status_error=None):
        self.chunks = chunks
        self.status_error = status_error

    def raise_for_status(self):
        if self.status_error:
            raise self.status_error

    def iter_content(self, chunk_size):
        return iter(self.chunks)


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.gets = []

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        return self.response


class RpaIoTests(unittest.TestCase):
    def test_unpack_gateway_result_accepts_files_envelope(self):
        io = load_module()
        result = {
            "success": True,
            "code": "200",
            "data": {
                "result_type": "files",
                "result_content": {
                    "status": "COMPLETED",
                    "failedInstances": 0,
                    "files": [{"fileUrl": "https://download.example/list.csv"}],
                },
            },
        }

        unpacked = io.unpack_gateway_result(result)

        self.assertEqual(unpacked.kind, "files")
        self.assertEqual(unpacked.file_url, "https://download.example/list.csv")

    def test_unpack_gateway_result_rejects_bad_files_envelopes(self):
        io = load_module()
        bad_cases = (
            (
                {
                    "success": False,
                    "code": "200",
                    "data": {"result_type": "files"},
                },
                "successful",
            ),
            (
                {
                    "success": True,
                    "code": "500",
                    "data": {"result_type": "files"},
                },
                "successful",
            ),
            (
                {
                    "success": True,
                    "code": "200",
                    "data": {
                        "result_type": "files",
                        "result_content": {
                            "status": "RUNNING",
                            "failedInstances": 0,
                            "files": [{"fileUrl": "https://x"}],
                        },
                    },
                },
                "complete",
            ),
            (
                {
                    "success": True,
                    "code": "200",
                    "data": {
                        "result_type": "files",
                        "result_content": {
                            "status": "COMPLETED",
                            "failedInstances": 1,
                            "files": [{"fileUrl": "https://x"}],
                        },
                    },
                },
                "complete",
            ),
            (
                {
                    "success": True,
                    "code": "200",
                    "data": {
                        "result_type": "files",
                        "result_content": {
                            "status": "COMPLETED",
                            "failedInstances": 0,
                            "files": [],
                        },
                    },
                },
                "fileUrl",
            ),
        )
        for payload, message in bad_cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(io.RpaIoError, message):
                    io.unpack_gateway_result(payload)

    def test_unpack_gateway_result_accepts_direct_payload_records(self):
        io = load_module()
        self.assertEqual(
            io.unpack_gateway_result(
                {"success": True, "data": [{"material_id": "1"}]}
            ).records,
            [{"material_id": "1"}],
        )
        self.assertEqual(
            io.unpack_gateway_result(
                {
                    "success": True,
                    "data": {
                        "result_type": "payload",
                        "payload": '[{"material_id":"2"}]',
                    },
                }
            ).records,
            [{"material_id": "2"}],
        )
        self.assertEqual(
            io.unpack_gateway_result([{"material_id": "3"}]).records,
            [{"material_id": "3"}],
        )

    def test_download_file_atomically_and_reject_empty_file(self):
        io = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "raw-csv" / "list.csv"
            session = FakeSession(FakeDownloadResponse([b"a,b\n1,2\n"]))
            path = io.download_file(
                "https://download.example/list.csv", target, session=session
            )

            self.assertEqual(path, target)
            self.assertEqual(target.read_text(encoding="utf-8"), "a,b\n1,2\n")
            self.assertEqual(session.gets[0][0], "https://download.example/list.csv")
            self.assertFalse(list(target.parent.glob("*.tmp")))

            with self.assertRaisesRegex(io.RpaIoError, "empty"):
                io.download_file(
                    "https://download.example/empty.csv",
                    Path(temporary_directory) / "empty.csv",
                    session=FakeSession(FakeDownloadResponse([])),
                )

    def test_materialize_local_artifact_requires_one_nonempty_csv(self):
        io = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            incoming = root / "incoming"
            incoming.mkdir()
            target = root / "raw-csv" / "list.csv"

            with self.assertRaisesRegex(io.RpaIoError, "missing"):
                io.materialize_local_artifact(incoming, target, suffix=".csv")

            first = incoming / "list-a.csv"
            first.write_text("material_id\n101\n", encoding="utf-8")
            self.assertEqual(
                io.materialize_local_artifact(incoming, target, suffix=".csv"), target
            )
            self.assertEqual(target.read_text(encoding="utf-8"), first.read_text(encoding="utf-8"))

            (incoming / "list-b.csv").write_text("material_id\n102\n", encoding="utf-8")
            with self.assertRaisesRegex(io.RpaIoError, "ambiguous"):
                io.materialize_local_artifact(incoming, target, suffix=".csv")

    def test_parse_csv_records_supports_common_delimiters_and_json_cells(self):
        io = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "list.csv"
            source.write_text(
                "material_id\x01object_index\x01tags\n"
                '101\x01{"ctr":0.5}\x01["轻食","便携"]\n',
                encoding="utf-8",
            )

            records = io.parse_csv_records(source)

            self.assertEqual(records[0]["material_id"], "101")
            self.assertEqual(records[0]["object_index"], {"ctr": 0.5})
            self.assertEqual(records[0]["tags"], ["轻食", "便携"])

    def test_parse_csv_records_ignores_delimiter_only_trailing_row(self):
        io = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "list.csv"
            source.write_text(
                "material_id\x01title\x01show_cnt\n"
                "101\x01有效素材\x01100\n"
                "\x02,,,,\n",
                encoding="utf-8",
            )

            records = io.parse_csv_records(source)

        self.assertEqual(
            records,
            [{"material_id": "101", "title": "有效素材", "show_cnt": "100"}],
        )

    def test_parse_csv_records_decodes_yuntu_python_literal_cells_from_fixture(self):
        io = load_module()

        records = io.parse_csv_records(FIXTURE_PATH)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["title"], "立夏养生提前吃起来")
        self.assertEqual(records[0]["show_cnt"], "40-50w")
        self.assertEqual(records[0]["object_index"]["ctr"], 0.0047685291)
        self.assertEqual(records[0]["object_index"]["show_cnt"], "418368")
        self.assertEqual(
            records[0]["people_tag_entry"][0]["tag_name_list"],
            ["新锐白领", "小镇青年"],
        )
        self.assertEqual(
            records[0]["material_tag_entry"][0]["tag_name_list"],
            ["限时抢购", "全场五折"],
        )

    def test_parse_csv_records_keeps_malformed_python_literal_as_text(self):
        io = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "malformed.csv"
            source.write_text(
                "material_id\x01object_index\n101\x01{'ctr': invalid}\n",
                encoding="utf-8",
            )

            records = io.parse_csv_records(source)

            self.assertEqual(records[0]["object_index"], "{'ctr': invalid}")

    def test_parse_csv_records_rejects_bad_headers_and_empty_files(self):
        io = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            empty = Path(temporary_directory) / "empty.csv"
            empty.write_text("material_id,title\n", encoding="utf-8")
            with self.assertRaisesRegex(io.RpaIoError, "no records"):
                io.parse_csv_records(empty)

            duplicate = Path(temporary_directory) / "duplicate.csv"
            duplicate.write_text("material_id,material_id\n1,2\n", encoding="utf-8")
            with self.assertRaisesRegex(io.RpaIoError, "duplicate"):
                io.parse_csv_records(duplicate)


if __name__ == "__main__":
    unittest.main()
