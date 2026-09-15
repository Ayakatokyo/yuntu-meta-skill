import unittest

from scripts import collector


class MaterialListSchemaTests(unittest.TestCase):
    def test_material_list_cannot_be_forwarded_as_rpa_business_params(self):
        with self.assertRaisesRegex(
            collector.RpaConnectorError,
            "unexpected list business parameters: material_list",
        ):
            collector.validate_list_business_params({
                "material_list": {"filters": [], "sort": None},
            })


if __name__ == "__main__":
    unittest.main()
