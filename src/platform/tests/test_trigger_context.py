"""Trigger-context field in silver.findings schema."""

import re
from pathlib import Path

from src.platform.schemas import silver_findings


def test_silver_findings_has_trigger_context_field():
    fields = {f.name: f for f in silver_findings.fields}
    assert "trigger_context" in fields, (
        "silver.findings must carry a trigger_context field to distinguish "
        "periodic-global and CI/CD-step scan results."
    )

    field = fields["trigger_context"]
    assert field.dataType.typeName() == "string"
    assert field.nullable is False, (
        "trigger_context must be non-null; default 'periodic' for legacy rows."
    )


def test_bootstrap_sql_declares_trigger_context_on_findings():
    repo_root = Path(__file__).resolve().parents[3]
    sql = repo_root.joinpath("src/platform/sql/silver_tables.sql").read_text()
    findings_match = re.search(
        r"CREATE TABLE IF NOT EXISTS silver\.findings.*?\) USING DELTA;",
        sql,
        re.DOTALL,
    )
    assert findings_match is not None, \
        "silver.findings DDL block missing from silver_tables.sql"
    assert "trigger_context" in findings_match.group(0), \
        "Bootstrap DDL for silver.findings must declare the trigger_context column."
