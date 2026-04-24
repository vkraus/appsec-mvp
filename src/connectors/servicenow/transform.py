"""ServiceNow transform: bronze rows of cmdb_ci_business_app to silver."""

from datetime import datetime, timezone
from pathlib import Path

from pyspark.sql import DataFrame, Row, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType

from src.common.config import SeverityMap, load_yaml
from src.common.schemas import silver_applications


_SEVERITY_PATH = Path(__file__).parents[3] / "config" / "severity" / "servicenow.yml"


_OWNED_BY_SCHEMA = StructType([
    StructField("email", StringType(), nullable=True),
])

_CMDB_BA_SCHEMA = StructType([
    StructField("sys_id", StringType(), nullable=False),
    StructField("name", StringType(), nullable=False),
    StructField("owned_by", _OWNED_BY_SCHEMA, nullable=True),
    StructField("u_criticality", StringType(), nullable=True),
    StructField("sys_updated_on", StringType(), nullable=False),
])


def _parse_sn_ts(raw: str) -> datetime:
    # ServiceNow format: "2026-04-20 10:00:00" UTC
    return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def _criticality_mapping_expr(column):
    """Return a Spark column expression that maps ServiceNow u_criticality
    values onto the canonical severity set via the declarative lookup at
    config/severity/servicenow.yml. Unknown inputs map to ``info``.
    """
    sev = load_yaml(SeverityMap, _SEVERITY_PATH)
    pairs = []
    for k, v in sev.root.items():
        pairs.extend([F.lit(k), F.lit(v)])
    return F.coalesce(F.create_map(*pairs)[column], F.lit("info"))


def transform(bronze_df: DataFrame) -> DataFrame:
    """Framework contract: bronze rows of cmdb_ci_business_app to silver.

    Parses the bronze envelope's ``_raw_payload`` against the cmdb fields
    consumed by the silver layer and projects onto
    ``silver_applications``. Criticality passes through the
    declarative lookup at ``config/severity/servicenow.yml``. Assumes
    ``owned_by`` is serialized as a struct with an ``email`` member; the
    Lakeflow-managed bronze view emits that shape by default.
    """
    parsed = bronze_df.withColumn(
        "r", F.from_json(F.col("_raw_payload"), _CMDB_BA_SCHEMA)
    )
    return parsed.select(
        F.col("r.sys_id").alias("application_id"),
        F.col("r.name").alias("name"),
        F.col("r.owned_by.email").alias("owner_email"),
        _criticality_mapping_expr(F.col("r.u_criticality")).alias("criticality"),
        F.to_timestamp(F.col("r.sys_updated_on"), "yyyy-MM-dd HH:mm:ss").alias("updated_at"),
    )


def business_apps_to_silver(spark: SparkSession, raw: list[dict]) -> DataFrame:
    """Direct path from a Python list of raw cmdb dicts to silver.

    Retained for test fixtures that bypass the bronze Delta table.
    Production jobs use ``transform(bronze_df)`` above.
    """
    sev = load_yaml(SeverityMap, _SEVERITY_PATH)
    rows = []
    for r in raw:
        owned_by = r.get("owned_by") or {}
        # ServiceNow returns reference fields as either {"value":...,"link":...,"email":...}
        # or as a bare string depending on sysparm_exclude_reference_link.
        owner_email = owned_by.get("email") if isinstance(owned_by, dict) else None
        rows.append(Row(
            application_id=r["sys_id"],
            name=r["name"],
            owner_email=owner_email,
            criticality=sev.root.get(r.get("u_criticality", ""), "info"),
            updated_at=_parse_sn_ts(r["sys_updated_on"]),
        ))
    return spark.createDataFrame(rows, schema=silver_applications)
