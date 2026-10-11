import os
import shutil
from pathlib import Path

# Never touch the real database or start the scheduler from tests
TEST_DIR = Path(__file__).resolve().parent.parent / "data" / "test"
shutil.rmtree(TEST_DIR, ignore_errors=True)
TEST_DIR.mkdir(parents=True, exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DIR / 'test.db'}"
os.environ["SCHEDULER_ENABLED"] = "false"
