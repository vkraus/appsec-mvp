# Databricks notebook source
# ruff: noqa: F821 — dbutils, spark are injected by the Databricks notebook runtime
"""Gold table: ``gold.cwe_owasp_heatmap``.

Cross-source CWE × OWASP Top 10:2021 heatmap of OPEN findings per
application. Answers: "which OWASP categories dominate each app's risk
surface, and which underlying CWEs drive each category?" — the
qualitative counterpart to severity-weighted risk posture.

Inputs:
    silver.findings              (cwe_id, repository_id, status_canonical,
                                  tool_source, category, file_path, …)
    silver.app_repo_mapping      (application_id, repository_id)
    silver.suppression_rules     (rule_id, scope, target_pattern, expires_at, …)

Output:
    gold.cwe_owasp_heatmap       (application_id, owasp_category, cwe_id,
                                  finding_count)

Logic:
    1. JOIN findings × app_repo_mapping on repository_id (LEFT). Findings
       whose repository_id is unmapped (or NULL) get
       ``application_id = '__UNMAPPED__'`` so they remain visible to
       operators rather than silently dropped.
    2. Apply suppression rules from silver.suppression_rules. Rules can
       scope by application_id (post-join), repository_id, tool_source,
       category, file_path, etc.
    3. Filter to ``status_canonical = 'open'``. Closed/resolved findings
       are not live risk and would distort the heatmap.
    4. Map each cwe_id → OWASP Top 10:2021 category via the canonical
       OWASP-published primary mapping (:data:`OWASP_2021_CWE_TO_CATEGORY`).
       Findings whose cwe_id is NULL or not in the mapping bucket as
       ``owasp_category = 'unmapped'``.
    5. Group by ``(application_id, owasp_category, cwe_id)`` and count.

The OWASP 2021 CWE list below is taken from the OWASP Foundation's
published primary mapping (https://owasp.org/Top10/, the "CWEs Mapped"
list under each category). It is canonical and must NOT be edited
without a corresponding update to the OWASP source.

Pure-Python helper :func:`compute_heatmap_rows` mirrors the Spark
transform and is unit-tested locally per CLAUDE.md (no local
SparkSession).
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

# ---------------------------------------------------------------------------
# Canonical OWASP Top 10:2021 → CWE primary mapping.
#
# Source: https://owasp.org/Top10/ — "CWEs Mapped" lists under each A-category.
# This is the OWASP Foundation's published primary mapping; do not invent
# additions. CWE IDs are stored as the canonical "CWE-<n>" string form
# matching :func:`src.platform.cwe._canonicalize`.

OWASP_2021_A01_BROKEN_ACCESS_CONTROL: frozenset[str] = frozenset({
    "CWE-22", "CWE-23", "CWE-35", "CWE-59", "CWE-200", "CWE-201",
    "CWE-219", "CWE-264", "CWE-275", "CWE-276", "CWE-284", "CWE-285",
    "CWE-352", "CWE-359", "CWE-377", "CWE-402", "CWE-425", "CWE-441",
    "CWE-497", "CWE-538", "CWE-540", "CWE-548", "CWE-552", "CWE-566",
    "CWE-601", "CWE-639", "CWE-651", "CWE-668", "CWE-706", "CWE-862",
    "CWE-863", "CWE-913", "CWE-922", "CWE-1275",
})

OWASP_2021_A02_CRYPTOGRAPHIC_FAILURES: frozenset[str] = frozenset({
    "CWE-261", "CWE-296", "CWE-310", "CWE-319", "CWE-321", "CWE-322",
    "CWE-323", "CWE-324", "CWE-325", "CWE-326", "CWE-327", "CWE-328",
    "CWE-329", "CWE-330", "CWE-331", "CWE-335", "CWE-336", "CWE-337",
    "CWE-338", "CWE-340", "CWE-347", "CWE-523", "CWE-720", "CWE-757",
    "CWE-759", "CWE-760", "CWE-780", "CWE-818", "CWE-916",
})

OWASP_2021_A03_INJECTION: frozenset[str] = frozenset({
    "CWE-20", "CWE-74", "CWE-75", "CWE-77", "CWE-78", "CWE-79", "CWE-80",
    "CWE-83", "CWE-87", "CWE-88", "CWE-89", "CWE-90", "CWE-91", "CWE-93",
    "CWE-94", "CWE-95", "CWE-96", "CWE-97", "CWE-98", "CWE-99", "CWE-100",
    "CWE-113", "CWE-116", "CWE-138", "CWE-184", "CWE-470", "CWE-471",
    "CWE-564", "CWE-610", "CWE-643", "CWE-644", "CWE-652", "CWE-917",
})

OWASP_2021_A04_INSECURE_DESIGN: frozenset[str] = frozenset({
    "CWE-73", "CWE-183", "CWE-209", "CWE-213", "CWE-235", "CWE-256",
    "CWE-257", "CWE-266", "CWE-269", "CWE-280", "CWE-311", "CWE-312",
    "CWE-313", "CWE-316", "CWE-419", "CWE-430", "CWE-434", "CWE-444",
    "CWE-451", "CWE-472", "CWE-501", "CWE-522", "CWE-525", "CWE-539",
    "CWE-579", "CWE-598", "CWE-602", "CWE-642", "CWE-646", "CWE-650",
    "CWE-653", "CWE-656", "CWE-657", "CWE-799", "CWE-807", "CWE-840",
    "CWE-841", "CWE-927", "CWE-1021", "CWE-1173",
})

OWASP_2021_A05_SECURITY_MISCONFIGURATION: frozenset[str] = frozenset({
    "CWE-2", "CWE-11", "CWE-13", "CWE-15", "CWE-16", "CWE-260", "CWE-315",
    "CWE-520", "CWE-526", "CWE-537", "CWE-541", "CWE-547", "CWE-611",
    "CWE-614", "CWE-756", "CWE-776", "CWE-942", "CWE-1004", "CWE-1032",
    "CWE-1174",
})

OWASP_2021_A06_VULNERABLE_AND_OUTDATED_COMPONENTS: frozenset[str] = frozenset({
    "CWE-937", "CWE-1035", "CWE-1104",
})

OWASP_2021_A07_IDENTIFICATION_AND_AUTHENTICATION_FAILURES: frozenset[str] = frozenset({
    "CWE-255", "CWE-259", "CWE-287", "CWE-288", "CWE-290", "CWE-294",
    "CWE-295", "CWE-297", "CWE-300", "CWE-302", "CWE-304", "CWE-306",
    "CWE-307", "CWE-346", "CWE-384", "CWE-521", "CWE-613", "CWE-620",
    "CWE-640", "CWE-798", "CWE-940", "CWE-1216",
})

OWASP_2021_A08_SOFTWARE_AND_DATA_INTEGRITY_FAILURES: frozenset[str] = frozenset({
    "CWE-345", "CWE-353", "CWE-426", "CWE-494", "CWE-502", "CWE-565",
    "CWE-784", "CWE-829", "CWE-830", "CWE-915",
})

OWASP_2021_A09_SECURITY_LOGGING_AND_MONITORING_FAILURES: frozenset[str] = frozenset({
    "CWE-117", "CWE-223", "CWE-532", "CWE-778",
})

OWASP_2021_A10_SERVER_SIDE_REQUEST_FORGERY: frozenset[str] = frozenset({
    "CWE-918",
})


def _build_cwe_to_category() -> dict[str, str]:
    """Invert the per-category sets into a flat ``cwe_id → category`` map.

    Built once at import time. Each CWE in the OWASP 2021 primary mapping
    appears under exactly one category; if a future revision introduces a
    duplicate, this will raise at import to surface the conflict early.
    """
    buckets: list[tuple[str, frozenset[str]]] = [
        ("A01", OWASP_2021_A01_BROKEN_ACCESS_CONTROL),
        ("A02", OWASP_2021_A02_CRYPTOGRAPHIC_FAILURES),
        ("A03", OWASP_2021_A03_INJECTION),
        ("A04", OWASP_2021_A04_INSECURE_DESIGN),
        ("A05", OWASP_2021_A05_SECURITY_MISCONFIGURATION),
        ("A06", OWASP_2021_A06_VULNERABLE_AND_OUTDATED_COMPONENTS),
        ("A07", OWASP_2021_A07_IDENTIFICATION_AND_AUTHENTICATION_FAILURES),
        ("A08", OWASP_2021_A08_SOFTWARE_AND_DATA_INTEGRITY_FAILURES),
        ("A09", OWASP_2021_A09_SECURITY_LOGGING_AND_MONITORING_FAILURES),
        ("A10", OWASP_2021_A10_SERVER_SIDE_REQUEST_FORGERY),
    ]
    out: dict[str, str] = {}
    for category, cwes in buckets:
        for cwe in cwes:
            if cwe in out:
                raise RuntimeError(
                    f"CWE {cwe} appears in both {out[cwe]} and {category}; "
                    "OWASP 2021 primary mapping should not double-assign."
                )
            out[cwe] = category
    return out


OWASP_2021_CWE_TO_CATEGORY: dict[str, str] = _build_cwe_to_category()

UNMAPPED_APPLICATION_ID = "__UNMAPPED__"
UNMAPPED_OWASP_CATEGORY = "unmapped"


# ---------------------------------------------------------------------------
# Pure-Python helper — exercised by pytest without a SparkSession.


def _classify_cwe(cwe_id: str | None) -> str:
    """Map a raw cwe_id to its OWASP 2021 category, or 'unmapped'.

    NULL / empty / unknown CWEs all bucket as ``UNMAPPED_OWASP_CATEGORY``
    so the heatmap surface remains non-lossy: every open finding shows up
    somewhere.
    """
    if cwe_id is None:
        return UNMAPPED_OWASP_CATEGORY
    return OWASP_2021_CWE_TO_CATEGORY.get(cwe_id, UNMAPPED_OWASP_CATEGORY)


def compute_heatmap_rows(
    findings_rows: Iterable[Mapping[str, Any]],
    app_repo_rows: Iterable[Mapping[str, Any]],
    suppression_rules: Iterable[Mapping[str, Any]] = (),
    now: Any = None,
) -> list[dict[str, Any]]:
    """Compute the CWE × OWASP heatmap as a list of row dicts.

    Args:
        findings_rows: Iterable of finding mappings. Required keys:
            ``cwe_id`` (may be None), ``repository_id`` (may be None),
            ``status_canonical``. Any additional keys (``tool_source``,
            ``category``, ``file_path`` …) flow through to the
            suppression-rule check.
        app_repo_rows: Iterable of mappings each carrying
            ``application_id`` and ``repository_id``. One repository may
            map to multiple applications (the row is duplicated per app
            on join, matching Spark LEFT JOIN semantics).
        suppression_rules: Iterable of suppression-rule mappings (see
            ``silver.suppression_rules`` schema). Applied AFTER the join
            so rules with ``scope = 'application_id'`` work. Defaults to
            empty.
        now: Reference timestamp for rule expiration. Defaults to
            ``datetime.now(timezone.utc)`` via
            :func:`src.analytics.lib.suppression.is_row_suppressed`.

    Returns:
        List of dicts, one per ``(application_id, owasp_category,
        cwe_id)`` group. Each row has keys ``application_id``,
        ``owasp_category``, ``cwe_id``, ``finding_count``.
    """
    from src.analytics.lib.suppression import is_row_suppressed

    # Index repository_id → list of application_ids (LEFT-JOIN semantics:
    # one repo can be linked to multiple apps).
    repo_to_apps: dict[str, list[str]] = {}
    for m in app_repo_rows:
        repo = m["repository_id"]
        app = m["application_id"]
        if repo is None or app is None:
            continue
        repo_to_apps.setdefault(repo, []).append(app)

    counts: dict[tuple[str, str, str | None], int] = {}

    for f in findings_rows:
        # 1. LEFT JOIN with app_repo_mapping. Unmapped → __UNMAPPED__.
        repo = f.get("repository_id")
        apps = repo_to_apps.get(repo, []) if repo is not None else []
        if not apps:
            apps = [UNMAPPED_APPLICATION_ID]

        for app in apps:
            # 2. Suppression — applied to the post-join row so rules with
            #    scope=application_id work.
            joined_row: dict[str, Any] = dict(f)
            joined_row["application_id"] = app
            if is_row_suppressed(joined_row, list(suppression_rules), now=now):
                continue

            # 3. Open-only filter.
            if f.get("status_canonical") != "open":
                continue

            # 4. CWE → OWASP classification. NULL or unknown → 'unmapped'.
            cwe = f.get("cwe_id")
            category = _classify_cwe(cwe)

            key = (app, category, cwe)
            counts[key] = counts.get(key, 0) + 1

    return [
        {
            "application_id": app,
            "owasp_category": category,
            "cwe_id": cwe,
            "finding_count": count,
        }
        for (app, category, cwe), count in counts.items()
    ]


# ---------------------------------------------------------------------------
# Notebook driver — Spark application path. Untested locally per CLAUDE.md.

# COMMAND ----------

dbutils.widgets.text("target_catalog", "")

target_catalog = dbutils.widgets.get("target_catalog")

# COMMAND ----------

from pyspark.sql import functions as F

from src.analytics.lib.suppression import apply_suppression_rules

silver_prefix = f"{target_catalog}.silver" if target_catalog else "silver"
gold_prefix = f"{target_catalog}.gold" if target_catalog else "gold"

findings = spark.read.table(f"{silver_prefix}.findings").select(
    "finding_id",
    "tool_source",
    "category",
    "status_canonical",
    "cwe_id",
    "repository_id",
    "file_path",
    "rule_id_native",
)
app_repo = spark.read.table(f"{silver_prefix}.app_repo_mapping").select(
    "application_id", "repository_id"
)
suppression_rules = spark.read.table(f"{silver_prefix}.suppression_rules")

# COMMAND ----------

# 1. LEFT JOIN findings × app_repo_mapping. Unmapped → __UNMAPPED__.
joined = findings.join(app_repo, on="repository_id", how="left").withColumn(
    "application_id",
    F.coalesce(F.col("application_id"), F.lit(UNMAPPED_APPLICATION_ID)),
)

# 2. Apply suppression — post-join so application_id-scoped rules work.
suppressed = apply_suppression_rules(joined, suppression_rules)

# 3. Open-only filter.
open_findings = suppressed.where(F.col("status_canonical") == "open")

# COMMAND ----------

# 4. CWE → OWASP classification via a CASE WHEN expression backed by the
#    canonical mapping. Built once on the driver, broadcast as a literal
#    map. Spark's ``create_map`` from a Python dict materialises the
#    lookup in the query plan; null cwe_id propagates through the
#    coalesce to 'unmapped'.

mapping_pairs: list[Any] = []
for cwe, category in OWASP_2021_CWE_TO_CATEGORY.items():
    mapping_pairs.append(F.lit(cwe))
    mapping_pairs.append(F.lit(category))

owasp_lookup = F.create_map(*mapping_pairs)

classified = open_findings.withColumn(
    "owasp_category",
    F.coalesce(owasp_lookup[F.col("cwe_id")], F.lit(UNMAPPED_OWASP_CATEGORY)),
)

# COMMAND ----------

# 5. Group + count.
result = (
    classified.groupBy("application_id", "owasp_category", "cwe_id")
    .agg(F.count(F.lit(1)).cast("int").alias("finding_count"))
    .select("application_id", "owasp_category", "cwe_id", "finding_count")
)

# COMMAND ----------

(
    result.write.format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(f"{gold_prefix}.cwe_owasp_heatmap")
)

print(f"wrote {gold_prefix}.cwe_owasp_heatmap")
