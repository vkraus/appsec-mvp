"""Bronze-to-silver transform for OWASP ZAP.

Per thesis section 4 Future Work, the declarative mapping for ZAP onto
``silver.findings`` is not yet implemented. This module honors the section
2.4.1 contract ``transform(bronze_df) -> silver_df`` by returning an empty
``silver_findings`` DataFrame so downstream orchestration can chain the call
without a runtime error. Replace with a real mapping when the ZAP rule catalog
is finalized.
"""
from __future__ import annotations

from pyspark.sql import DataFrame

from src.common.schemas import silver_findings


def transform(bronze_df: DataFrame) -> DataFrame:
    """Framework contract wrapper. Returns an empty silver_findings frame."""
    return bronze_df.sparkSession.createDataFrame([], schema=silver_findings)
