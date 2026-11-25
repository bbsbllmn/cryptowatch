import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "dags", ROOT):
    sys.path.insert(0, str(p))
os.environ.setdefault("AIRFLOW_HOME", tempfile.mkdtemp(prefix="airflow_test_"))
os.environ.setdefault("AIRFLOW__CORE__LOAD_EXAMPLES", "False")
os.environ.setdefault("AIRFLOW__CORE__UNIT_TEST_MODE", "True")
os.environ.setdefault("CW_PROJECT", "test-project")
