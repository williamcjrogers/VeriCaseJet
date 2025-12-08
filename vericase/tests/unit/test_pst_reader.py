# test_pst_reader.py

import unittest
from src.core.pst_reader import PSTReader


class TestPSTReader(unittest.TestCase):

    def setUp(self):
        self.pst_reader = PSTReader()

    def test_read_pst_file(self):
        # Assuming a method read_file exists in PSTReader
        result = self.pst_reader.read_file("path/to/test.pst")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)  # Assuming it returns a dictionary

    def test_extract_data(self):
        # Assuming a method extract_data exists in PSTReader
        self.pst_reader.read_file("path/to/test.pst")
        data = self.pst_reader.extract_data()
        self.assertIn("emails", data)  # Assuming it extracts emails
        self.assertGreater(len(data["emails"]), 0)

    def test_invalid_file(self):
        with self.assertRaises(FileNotFoundError):
            self.pst_reader.read_file("path/to/invalid.pst")


if __name__ == "__main__":
    unittest.main()
