"""Trigger-context field in silver.findings schema."""

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
    sql = Path(__file__).resolve().parents[2].joinpath("sql/bootstrap/schemas.sql").read_text()
    assert "trigger_context" in sql, \
        "Bootstrap DDL for silver.findings must declare the trigger_context column."
