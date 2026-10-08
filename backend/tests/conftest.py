import os
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(__file__).parent / "test.db")
os.environ["AGENT_TOKEN"] = "test-token"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["SEARCH_PROVIDER"] = "none"
os.environ["ENABLE_SCHEDULER"] = "false"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
