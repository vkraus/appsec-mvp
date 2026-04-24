"""Silver-layer helpers: severity/status normalization and
category-conditional deduplication.

SAST dedup tuple: (repository_id, file_path, start_line, cwe_id) when cwe is
present, else (repository_id, file_path, start_line, tool_source,
rule_id_native) for intra-tool fallback.

DAST dedup tuple: (url, rule_id_native)."""

from pyspark.sql import DataFrame, functions as F

from src.common.config import SeverityMap, StatusMap


_SEVERITY_RANK = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
    "info": 0,
}


def normalize_severity(native: str, mapping: SeverityMap) -> str:
    return mapping.root.get(native, "info")


def normalize_status(native: str, mapping: StatusMap) -> str:
    return mapping.root.get(native, "open")


def dedup_findings(df: DataFrame) -> DataFrame:
    sast = df.filter((F.col("category") == "sast") & F.col("cwe_id").isNotNull())
    sast_fallback = df.filter((F.col("category") == "sast") & F.col("cwe_id").isNull())
    dast = df.filter(F.col("category") == "dast")
    other = df.filter(~F.col("category").isin("sast", "dast"))

    sast_keys = ["repository_id", "file_path", "start_line", "cwe_id"]
    sast_fb_keys = ["repository_id", "file_path", "start_line", "tool_source", "rule_id_native"]
    dast_keys = ["url", "rule_id_native"]

    return (
        _collapse(sast, sast_keys)
        .unionByName(_collapse(sast_fallback, sast_fb_keys), allowMissingColumns=True)
        .unionByName(_collapse(dast, dast_keys), allowMissingColumns=True)
        .unionByName(_collapse(other, ["finding_id"]), allowMissingColumns=True)
    )


def _collapse(df: DataFrame, keys: list[str]) -> DataFrame:
    if df.rdd.isEmpty():
        # Preserve schema for empty unions
        return df.withColumn("tool_sources", F.array(F.col("tool_source")))
    sev_rank_expr = F.create_map(
        *[x for k, v in _SEVERITY_RANK.items() for x in (F.lit(k), F.lit(v))]
    )
    df = df.withColumn("_sev_rank", sev_rank_expr[F.col("severity_canonical")])
    key_set = set(keys)
    w_keys = [F.col(k) for k in keys]

    # Non-key nullable columns that are collapsed via first()
    _first_cols = ["finding_id", "category", "tool_source", "status_canonical",
                   "cwe_id", "rule_id_native", "repository_id", "file_path", "start_line", "url"]

    agg_exprs = [
        F.collect_set("tool_source").alias("tool_sources"),
        F.element_at(
            F.sort_array(F.collect_list(F.struct("_sev_rank", "severity_canonical")), asc=False),
            1,
        )["severity_canonical"].alias("severity_canonical"),
        F.min("first_seen_at").alias("first_seen_at"),
        F.max("last_seen_at").alias("last_seen_at"),
    ]
    for col_name in _first_cols:
        if col_name not in key_set:
            agg_exprs.append(F.first(col_name).alias(col_name))

    return df.groupBy(*w_keys).agg(*agg_exprs)
