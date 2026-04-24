"""GitHub transform: bronze envelope rows → silver entity frames."""

from datetime import datetime

from pyspark.sql import DataFrame, Row, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType

from src.common.schemas import silver_repositories


_RAW_REPO_SCHEMA = StructType([
    StructField("full_name", StringType(), nullable=True),
    StructField("default_branch", StringType(), nullable=True),
    StructField("updated_at", StringType(), nullable=True),
])


def _parse_iso(ts: str) -> datetime:
    # GitHub returns ISO-8601 with trailing Z
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def transform(bronze_df: DataFrame) -> DataFrame:
    """Framework contract: bronze rows of GitHub repositories to silver.

    Parses the bronze envelope's ``_raw_payload`` column against the known
    repository fields and projects onto ``silver_repositories``. Honors
    the section 2.4.1 signature ``transform(bronze_df) -> silver_df`` so
    downstream jobs can load the bronze table and call this directly.
    """
    parsed = bronze_df.withColumn(
        "r", F.from_json(F.col("_raw_payload"), _RAW_REPO_SCHEMA)
    )
    return parsed.select(
        F.col("r.full_name").alias("repository_id"),
        F.col("r.full_name").alias("full_name"),
        F.col("r.default_branch").alias("default_branch"),
        F.to_timestamp(F.col("r.updated_at")).alias("updated_at"),
    )


def repositories_to_silver(spark: SparkSession, raw: list[dict]) -> DataFrame:
    """Direct path from a Python list of raw repo dicts to silver.

    Retained for the test fixture that bypasses the bronze Delta table.
    Production jobs use ``transform(bronze_df)`` above.
    """
    rows = [
        Row(
            repository_id=r["full_name"],
            full_name=r["full_name"],
            default_branch=r.get("default_branch"),
            updated_at=_parse_iso(r["updated_at"]),
        )
        for r in raw
    ]
    return spark.createDataFrame(rows, schema=silver_repositories)
