"""PySpark schemas for Silver-layer tables. Authoritative for column
names, types, and nullability. Bronze is schema-on-read; Gold is derived.

Table and column names follow the thesis section 2.2.2 inventory. The MVP
realizes the subset named in the framework-scope paragraph of that section:
``applications``, ``repositories``, ``findings``, ``app_repo_mapping``.
"""

from pyspark.sql.types import (
    IntegerType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

silver_applications = StructType([
    StructField("application_id", StringType(), nullable=False),
    StructField("name", StringType(), nullable=False),
    StructField("owner_email", StringType(), nullable=True),
    StructField("criticality", StringType(), nullable=True),
    StructField("updated_at", TimestampType(), nullable=False),
])


silver_repositories = StructType([
    StructField("repository_id", StringType(), nullable=False),
    StructField("full_name", StringType(), nullable=False),
    StructField("default_branch", StringType(), nullable=True),
    StructField("updated_at", TimestampType(), nullable=False),
])


silver_app_repo_mapping = StructType([
    StructField("application_id", StringType(), nullable=False),
    StructField("repository_id", StringType(), nullable=False),
    StructField("linked_at", TimestampType(), nullable=False),
])


silver_findings = StructType([
    StructField("finding_id", StringType(), nullable=False),
    StructField("tool_source", StringType(), nullable=False),
    StructField("category", StringType(), nullable=False),
    StructField("severity_canonical", StringType(), nullable=False),
    StructField("status_canonical", StringType(), nullable=False),
    StructField("cwe_id", StringType(), nullable=True),
    StructField("cve_id", StringType(), nullable=True),
    StructField("rule_id_native", StringType(), nullable=False),
    StructField("trigger_context", StringType(), nullable=False),
    StructField("repository_id", StringType(), nullable=True),
    StructField("file_path", StringType(), nullable=True),
    StructField("start_line", IntegerType(), nullable=True),
    StructField("url", StringType(), nullable=True),
    StructField("first_seen_at", TimestampType(), nullable=False),
    StructField("last_seen_at", TimestampType(), nullable=False),
])


silver_finding_location = StructType([
    StructField("finding_id", StringType(), nullable=False),
    StructField("repository_id", StringType(), nullable=True),
    StructField("commit_sha", StringType(), nullable=True),
    StructField("file_path", StringType(), nullable=True),
    StructField("start_line", IntegerType(), nullable=True),
    StructField("end_line", IntegerType(), nullable=True),
    StructField("url", StringType(), nullable=True),
])


# Suppression rules — INSERT-only operator-authored rows that mute findings
# at Gold-layer aggregation time. Silver retains the canonical immutable
# record; suppression is an analytics-layer concern (see
# src/analytics/lib/suppression.py and mkdocs/docs/analytics/suppression-rules.md).
silver_suppression_rules = StructType([
    StructField("rule_id", StringType(), nullable=False),
    StructField("scope", StringType(), nullable=False),
    StructField("target_pattern", StringType(), nullable=False),
    StructField("expires_at", TimestampType(), nullable=False),
    StructField("reason", StringType(), nullable=True),
    StructField("created_by", StringType(), nullable=False),
    StructField("created_at", TimestampType(), nullable=False),
])
