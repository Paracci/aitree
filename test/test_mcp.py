import unittest
import json
from pathlib import Path
from aitree.server import (
    aitree_get_tree,
    aitree_read_file,
    aitree_get_stats,
    aitree_get_changed
)

class TestMCPTools(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent.parent
        
    def test_get_tree(self):
        res = aitree_get_tree(str(self.root), format="json")
        data = json.loads(res)
        self.assertIn("tree", data)
        self.assertIn("stats", data)
        
    def test_read_file(self):
        res = aitree_read_file(str(self.root), "README.md")
        data = json.loads(res)
        if "error" in data:
            self.fail(f"read_file returned error: {data['error']}")
        self.assertIn("content", data)
        self.assertTrue("AITree" in data["content"])
        
    def test_read_file_path_traversal(self):
        res = aitree_read_file(str(self.root), "../README.md")
        data = json.loads(res)
        self.assertIn("error", data)
        
    def test_get_stats(self):
        res = aitree_get_stats(str(self.root))
        data = json.loads(res)
        self.assertIn("files", data)
        self.assertTrue(data["files"] > 0)
        
    def test_get_changed(self):
        res = aitree_get_changed(str(self.root))
        try:
            data = json.loads(res)
        except Exception:
            self.fail("Output is not valid JSON")

if __name__ == "__main__":
    unittest.main()
