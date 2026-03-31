import unittest
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent))

# Test modules will be added here
# from test_core import TestCore, ...

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)