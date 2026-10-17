import os
import sys

os.environ["DARWIN_MOCK"] = "1"          # never call a real API from tests
os.environ.setdefault("DARWIN_BUDGET", "100")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
