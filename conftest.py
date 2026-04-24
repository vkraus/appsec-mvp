"""Root conftest.py — ensure PySpark workers use the same Python interpreter
as the pytest process, avoiding version mismatches on machines where multiple
Python installations are present."""

import os
import sys

os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)
