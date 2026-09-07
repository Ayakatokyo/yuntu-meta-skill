import unittest

from scripts import collector


class MaterialListSchemaTests(unittest.TestCase):
    def test_schema_exposes_material_list_and_keeps_it_out_of_rpa_fields(self):
        self.assertIn("material_list", collector.BUSINESS_PARAMS_SCHEMA["query_spec"])
        self.assertNotIn("material_list", collector.LIST_FIELDS)
        self.assertNotIn("material_list", collector.BUSINESS_PARAMS_SCHEMA["list_fields"])
        self.assertFalse(collector.BUSINESS_PARAMS_SCHEMA["query_spec"]["material_list"]["remote_api"])


if __name__ == "__main__":
    unittest.main()
