"""Contract: every PySpark struct in `src/platform/schemas.py` whose name
shadows a `CREATE TABLE silver.<x>` block in `src/platform/sql/silver_tables.sql`
MUST share the same column set with the same nullability.

Why: writes from connector transforms target the table created by the
bootstrap DDL. If the DDL has a NOT NULL column the struct doesn't emit, or
declares a column the struct doesn't carry, runtime writes fail. This test
makes the contract explicit so drift is caught at unit-test time.

Skip cases: tables in the DDL that have no matching schema struct (e.g.
`silver.hwm`, `silver.waf_events`) are intentional — see the comments in
`schemas.py` and `silver_tables.sql`. Add them here only when a struct also
ships in `schemas.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.platform import schemas

# (struct attribute on `schemas`, fully qualified DDL table name)
PAIRS = [
    ("silver_findings", "silver.findings"),
    ("silver_repositories", "silver.repositories"),
    ("silver_applications", "silver.applications"),
    ("silver_app_repo_mapping", "silver.app_repo_mapping"),
    ("silver_finding_location", "silver.finding_location"),
    ("silver_suppression_rules", "silver.suppression_rules"),
]

DDL_PATH = Path(__file__).resolve().parents[3] / "src/platform/sql/silver_tables.sql"

# Maps PySpark dataType.typeName() to SQL type tokens accepted in the DDL.
TYPE_ALIASES = {
    "string": {"string"},
    "integer": {"int", "integer"},
    "long": {"bigint", "long"},
    "timestamp": {"timestamp"},
}


def _parse_ddl_block(ddl: str, table: str) -> list[tuple[str, str, bool]]:
    """Return [(col_name, sql_type_lower, nullable)] for the named table."""
    pattern = re.compile(
        rf"CREATE TABLE IF NOT EXISTS {re.escape(table)}\s*\((.*?)\)\s*USING DELTA;",
        re.DOTALL,
    )
    m = pattern.search(ddl)
    if not m:
        raise AssertionError(f"DDL block for {table} not found in silver_tables.sql")
    body = m.group(1)
    cols: list[tuple[str, str, bool]] = []
    for raw in body.splitlines():
        line = raw.split("--", 1)[0].strip().rstrip(",")
        if not line:
            continue
        tokens = line.split()
        name = tokens[0].lower()
        sql_type = tokens[1].lower() if len(tokens) > 1 else ""
        not_null = "not null" in line.lower()
        cols.append((name, sql_type, not not_null))
    return cols


@pytest.fixture(scope="module")
def ddl_text() -> str:
    return DDL_PATH.read_text()


@pytest.mark.parametrize("struct_attr,table", PAIRS)
def test_struct_matches_ddl(struct_attr: str, table: str, ddl_text: str) -> None:
    struct = getattr(schemas, struct_attr)
    struct_cols = [
        (f.name.lower(), f.dataType.typeName().lower(), f.nullable)
        for f in struct.fields
    ]
    ddl_cols = _parse_ddl_block(ddl_text, table)

    struct_names = [c[0] for c in struct_cols]
    ddl_names = [c[0] for c in ddl_cols]
    assert struct_names == ddl_names, (
        f"Column ordering / membership mismatch for {table}:\n"
        f"  schemas.py: {struct_names}\n"
        f"  DDL:        {ddl_names}"
    )

    for (sname, stype, snullable), (dname, dtype, dnullable) in zip(
        struct_cols, ddl_cols
    ):
        accepted = TYPE_ALIASES.get(stype, {stype})
        assert dtype in accepted, (
            f"{table}.{sname}: schema type {stype!r} not satisfied by DDL "
            f"type {dtype!r} (accepted: {sorted(accepted)})"
        )
        assert snullable == dnullable, (
            f"{table}.{sname}: nullability mismatch — "
            f"schemas.py nullable={snullable}, DDL nullable={dnullable}"
        )
