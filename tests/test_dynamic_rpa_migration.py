import importlib.util
from pathlib import Path
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_client(filename, module_name):
    path = ROOT / "scripts" / filename
    if not path.is_file():
        raise AssertionError(f"dynamic RPA client is missing: {filename}")
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.workspace_root = ROOT
    return module


class DynamicRpaMigrationTests(unittest.TestCase):
    def test_list_client_has_yuntu_resource_default(self):
        client = load_client("rpa_dynamic_client.py", "yuntu_dynamic_list_client")

        self.assertEqual(
            client.CONNECTOR_CODE,
            "rpa.conn.juliang.yt.industry.content.rankings.list",
        )
        self.assertEqual(client.default_output_dir().relative_to(ROOT).parts[0], "云图数据资源")

    def test_detail_client_has_yuntu_resource_default(self):
        client = load_client("rpa_dynamic_detail_client.py", "yuntu_dynamic_detail_client")

        self.assertEqual(
            client.CONNECTOR_CODE,
            "rpa.conn.juliang.yt.industry.content.rankings.details",
        )
        self.assertEqual(client.default_output_dir().relative_to(ROOT).parts[0], "云图数据资源")

    def test_clients_preserve_legacy_session_cookie_fallback(self):
        for filename, module_name in (
            ("rpa_dynamic_client.py", "yuntu_dynamic_list_auth_client"),
            ("rpa_dynamic_detail_client.py", "yuntu_dynamic_detail_auth_client"),
        ):
            with self.subTest(filename=filename):
                client = load_client(filename, module_name)
                with mock.patch.dict(client.os.environ, {
                    "ENV_BACKEND_HOST": "https://gateway.test",
                    "YUCE_AUTHORIZATION": "authorization",
                    "YCSESSIONID": "legacy-session",
                }, clear=True):
                    runtime = client.runtime_config(require_session=True)
                self.assertEqual(runtime["session_id"], "legacy-session")
                self.assertEqual(runtime["cookies"], {"YCSESSIONID": "legacy-session"})


if __name__ == "__main__":
    unittest.main()
