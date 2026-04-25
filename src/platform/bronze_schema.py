"""Bronze metadata envelope for thesis section 2.2.2.

Every framework-owned bronze write stamps the uniform envelope defined
in section 2.2.2. The envelope is additive. Source-native columns
survive unchanged. The five envelope columns are prepended as a prefix.
On tables with no high-water mark (push-driven, one-shot artifacts
that are fully rewritten), ``_hwm_value`` is omitted.

For sources where the bronze schema is not framework-owned (Lakeflow
Connect pipelines), the envelope is synthesized in a downstream SQL
view that reads the Lakeflow-managed ingestion columns; see
``src/connectors/<source>/sql/*_envelope.sql``.
"""
from __future__ import annotations

from typing import Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

BRONZE_ENVELOPE_COLUMNS: tuple[str, ...] = (
    "_ingestion_timestamp",
    "_source_system",
    "_batch_id",
    "_raw_payload",
    "_hwm_value",
)


def with_envelope(
    df: DataFrame,
    *,
    source_system: str,
    batch_id: str,
    hwm_value: Optional[str],
) -> DataFrame:
    """Return ``df`` prefixed with the bronze envelope columns.

    Args:
        df: Source-native bronze dataframe (any schema).
        source_system: Value for ``_source_system`` (e.g. ``"owasp_zap"``).
        batch_id: Value for ``_batch_id``. This is the run identifier.
        hwm_value: High-water mark for ``_hwm_value``. Pass None to omit
            the column entirely (push or full-rewrite tables).
    """
    source_columns = df.columns
    payload = F.to_json(F.struct(*[F.col(c) for c in source_columns]))

    out = (
        df.withColumn("_ingestion_timestamp", F.current_timestamp())
        .withColumn("_source_system", F.lit(source_system))
        .withColumn("_batch_id", F.lit(batch_id))
        .withColumn("_raw_payload", payload)
    )
    if hwm_value is not None:
        out = out.withColumn("_hwm_value", F.lit(hwm_value))

    envelope_prefix = [c for c in BRONZE_ENVELOPE_COLUMNS if c in out.columns]
    return out.select(*envelope_prefix, *source_columns)
