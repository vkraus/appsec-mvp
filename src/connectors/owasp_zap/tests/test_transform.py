"""OWASP ZAP bronze-to-silver transform tests.

REQ-ID coverage (per catalog matrix at mkdocs/docs/platform/reference/catalog.md
lines 39-50; ZAP's prior PASS profile is REQ-TRF-MAP/SEV/STS/TS=PASS,
REQ-DQ=PASS, REQ-DEDUP=PASS):

- REQ-TRF-MAP: ZAP scan-report fields project onto silver_findings with
  correct types and DAST-shape null handling (file_path / start_line /
  cve_id / repository_id all null; url carries per-instance URI;
  rule_id_native carries the plugin id).
- REQ-TRF-SEV: every documented ZAP risk level (Informational, Low,
  Medium, High) maps to the canonical four-level model; undocumented
  values fall through to the platform default.
- REQ-TRF-STS: ZAP has no native lifecycle. Every alert lands as `open`;
  transition to `resolved` is computed at the Silver layer by absence
  in successive scans.
- REQ-TRF-TS: @generated is parsed as UTC; first_seen_at and
  last_seen_at are timezone-aware. Missing @generated falls back to
  the run's wall-clock UTC.
- REQ-DQ: rows with no pluginid / no site / no instance uri are dropped
  at the transform gate.
- REQ-DEDUP: the dedup key is (target, alert_id, uri_path) per
  references/dast.md; encoded literally in transform.dedup_key_for and
  in mapping.yml.

Tests exercising the framework's silver schema use a local Spark
session, matching the established pattern in
src/connectors/sonarqube/tests/test_transform.py. Pure-logic tests
(severity / cwe normalisation, dedup-key tuple, target-split) run
without Spark.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from pyspark.sql import SparkSession

from src.connectors.owasp_zap.transform import (
    _extract_risk,
    _normalize_cwe,
    _split_target,
    alerts_to_silver,
    apply_deployments_join,
    dedup_key_for,
)
from src.platform.config import SeverityMap, StatusMap, load_yaml
from src.platform.silver import normalize_severity, normalize_status

FIX = Path(__file__).parent / "fixtures"

_CONNECTOR_DIR = Path(__file__).parents[1]
_SEV_PATH = _CONNECTOR_DIR / "severity.yml"
_STATUS_PATH = _CONNECTOR_DIR / "status.yml"
_CONFIG_PATH = _CONNECTOR_DIR / "config.yml"
_MAPPING_PATH = _CONNECTOR_DIR / "mapping.yml"


@pytest.fixture(scope="module")
def spark() -> SparkSession:
    return (
        SparkSession.builder.appName("owasp-zap-tests")
        .master("local[2]")
        .config("spark.sql.shuffle.partitions", "1")
        .getOrCreate()
    )


def _load_scan_report() -> dict:
    return json.loads((FIX / "scan_report.json").read_text())


# ---------------------------------------------------------------------------
# REQ-TRF-MAP: schema mapping
# ---------------------------------------------------------------------------


@pytest.mark.requirement("REQ-TRF-MAP")
def test_alert_mapping(spark: SparkSession) -> None:
    """REQ-TRF-MAP: ZAP scan-report fields project onto silver_findings
    with correct types, values, and DAST-shape null handling
    (file_path / start_line / cve_id / repository_id null; url
    carries the per-instance URI; rule_id_native carries the plugin id).
    """
    raw = [_load_scan_report()]
    rows = alerts_to_silver(spark, raw).collect()
    by_id = {r["finding_id"]: r for r in rows}

    # 4 alerts; one alert has 2 instances -> 5 rows total.
    assert len(rows) == 5

    row = by_id["40012@https://app.test/search"]
    assert row["tool_source"] == "owasp_zap"
    assert row["category"] == "dast"
    assert row["rule_id_native"] == "40012"
    assert row["url"] == "https://app.test/search"
    # DAST shape — file/line/cve/repo all null.
    assert row["file_path"] is None
    assert row["start_line"] is None
    assert row["cve_id"] is None
    assert row["repository_id"] is None
    # cweid="79" -> projected verbatim (CWE-prefixing is enrichment-side).
    assert row["cwe_id"] == "79"
    # trigger_context defaults to "cicd" for the MVP CI/CD-step path.
    assert row["trigger_context"] == "cicd"


@pytest.mark.requirement("REQ-TRF-MAP")
def test_finding_id_composition_per_mapping_yml(spark: SparkSession) -> None:
    """REQ-TRF-MAP: mapping.yml declares finding_id: pluginid + "@" + uri.
    Two instances of the same alert at distinct URIs must produce
    distinct finding_ids.
    """
    raw = [_load_scan_report()]
    out = {r["finding_id"]: r for r in alerts_to_silver(spark, raw).collect()}

    assert "10202@https://app.test/api/users" in out
    assert "10202@https://app.test/api/users/42" in out
    assert (
        out["10202@https://app.test/api/users"]["url"]
        != out["10202@https://app.test/api/users/42"]["url"]
    )


@pytest.mark.requirement("REQ-TRF-MAP")
def test_cweid_placeholder_collapses_to_null() -> None:
    """REQ-TRF-MAP: ZAP emits cweid="0" (and occasionally "-1") for
    findings with no CWE classification. Those values are placeholders
    and must collapse to NULL rather than appearing as a literal '0'
    CWE.
    """
    assert _normalize_cwe(None) is None
    assert _normalize_cwe("") is None
    assert _normalize_cwe("0") is None
    assert _normalize_cwe("-1") is None
    assert _normalize_cwe("79") == "79"
    assert _normalize_cwe(200) == "200"


@pytest.mark.requirement("REQ-TRF-MAP")
def test_mapping_yml_dedup_key_shape() -> None:
    """REQ-TRF-MAP: mapping.yml declares the DAST dedup-key tuple
    (target, alert_id, uri_path) — the literal encoding of the category
    invariant in references/dast.md.
    """
    mapping = yaml.safe_load(_MAPPING_PATH.read_text())
    assert mapping["dedup_key"] == ["target", "alert_id", "uri_path"]
    assert mapping["target_silver_table"] == "silver.findings"
    assert mapping["fields"]["category"] == "dast"


# ---------------------------------------------------------------------------
# REQ-TRF-SEV: severity normalization
# ---------------------------------------------------------------------------


@pytest.mark.requirement("REQ-TRF-SEV")
def test_severity_normalization_all_four_levels() -> None:
    """REQ-TRF-SEV: all four ZAP risk levels normalize to canonical
    severity. ZAP has no direct `critical` equivalent; promotion is
    driven downstream by CWE class and KEV overlap rules in the
    canonical-mapping layer (see severity.yml header comment).
    """
    sev = load_yaml(SeverityMap, _SEV_PATH)
    assert normalize_severity("Informational", sev) == "info"
    assert normalize_severity("Low", sev) == "low"
    assert normalize_severity("Medium", sev) == "medium"
    assert normalize_severity("High", sev) == "high"


@pytest.mark.requirement("REQ-TRF-SEV")
def test_severity_undocumented_falls_through_to_default() -> None:
    """REQ-TRF-SEV: an undocumented severity value falls through to the
    `info` default (per src.platform.silver.normalize_severity)
    rather than crashing or masquerading as a known level.
    """
    sev = load_yaml(SeverityMap, _SEV_PATH)
    assert normalize_severity("Catastrophic", sev) == "info"


@pytest.mark.requirement("REQ-TRF-SEV")
def test_riskdesc_split_extracts_risk_token() -> None:
    """REQ-TRF-SEV: ZAP's JSON report carries the four-level risk inside
    riskdesc as "<Risk> (<Confidence>)". The leading token is the risk
    level used for severity lookup.
    """
    assert _extract_risk("Medium (Medium)") == "Medium"
    assert _extract_risk("High (Low)") == "High"
    assert _extract_risk("Informational (Medium)") == "Informational"
    assert _extract_risk("Low") == "Low"
    assert _extract_risk("") is None
    assert _extract_risk(None) is None


@pytest.mark.requirement("REQ-TRF-SEV")
def test_severity_round_trip_via_alerts_to_silver(spark: SparkSession) -> None:
    """REQ-TRF-SEV: end-to-end check — the four-row fixture covers all
    four risk levels, and the output severity_canonical column matches
    the four-level canonical model.
    """
    raw = [_load_scan_report()]
    by_id = {r["finding_id"]: r for r in alerts_to_silver(spark, raw).collect()}

    assert by_id["40012@https://app.test/search"]["severity_canonical"] == "high"
    assert by_id["10202@https://app.test/api/users"]["severity_canonical"] == "medium"
    assert by_id["10038@https://app.test/"]["severity_canonical"] == "low"
    assert by_id["10049@https://app.test/static/main.js"]["severity_canonical"] == "info"


# ---------------------------------------------------------------------------
# REQ-TRF-STS: status normalization
# ---------------------------------------------------------------------------


@pytest.mark.requirement("REQ-TRF-STS")
def test_status_always_open(spark: SparkSession) -> None:
    """REQ-TRF-STS: ZAP has no server-side lifecycle. Per status.yml,
    every finding lands as `open`. Transition to `resolved` is
    computed at the Silver layer by absence in successive scans.
    """
    raw = [_load_scan_report()]
    rows = alerts_to_silver(spark, raw).collect()
    assert {r["status_canonical"] for r in rows} == {"open"}


@pytest.mark.requirement("REQ-TRF-STS")
def test_status_lookup_default_open() -> None:
    """REQ-TRF-STS: any unrecognized status falls through to `open`
    per src.platform.silver.normalize_status. (ZAP only ever supplies
    "open" because status.yml is a single-entry map; this asserts the
    default contract.)
    """
    status = load_yaml(StatusMap, _STATUS_PATH)
    assert normalize_status("UNKNOWN_STATE", status) == "open"
    assert normalize_status("open", status) == "open"


# ---------------------------------------------------------------------------
# REQ-TRF-TS: timestamp normalization
# ---------------------------------------------------------------------------


@pytest.mark.requirement("REQ-TRF-TS")
def test_first_seen_at_is_utc_aware(spark: SparkSession) -> None:
    """REQ-TRF-TS: first_seen_at and last_seen_at are emitted as
    timezone-aware UTC datetimes. The fixture's @generated string
    ("Tue, 21 Apr 2026 10:00:00") has no offset and is treated as
    UTC at the Bronze layer.
    """
    raw = [_load_scan_report()]
    rows = alerts_to_silver(spark, raw).collect()

    expected = datetime(2026, 4, 21, 10, 0, tzinfo=UTC)
    for row in rows:
        assert row["first_seen_at"] == expected
        assert row["last_seen_at"] == expected
        assert row["first_seen_at"].tzinfo is not None
        assert row["last_seen_at"].tzinfo is not None


@pytest.mark.requirement("REQ-TRF-TS")
def test_missing_generated_falls_back_to_now(spark: SparkSession) -> None:
    """REQ-TRF-TS: when @generated is absent the connector stamps
    a fallback timestamp (the run's wall-clock UTC). The fallback is
    accepted by callers that pass a deterministic fallback_now.
    """
    fixed = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    raw = [
        {
            "site": [
                {
                    "@name": "https://app.test",
                    "alerts": [
                        {
                            "pluginid": "10202",
                            "riskdesc": "Medium (Medium)",
                            "cweid": "200",
                            "instances": [{"uri": "https://app.test/x"}],
                        }
                    ],
                }
            ]
        }
    ]
    rows = alerts_to_silver(spark, raw, fallback_now=fixed).collect()
    assert rows[0]["first_seen_at"] == fixed


# ---------------------------------------------------------------------------
# REQ-DQ: data-quality expectation
# ---------------------------------------------------------------------------


@pytest.mark.requirement("REQ-DQ")
def test_findings_expectation_quarantines_malformed(spark: SparkSession) -> None:
    """REQ-DQ: malformed records are dropped at the transform gate.
    A row missing pluginid, missing the scanned site, or with an
    instance that has no uri cannot land in Silver: the synthetic
    finding_id (pluginid@uri) is non-nullable and the dedup tuple
    (target, alert_id, uri_path) requires all three.

    On Databricks, an equivalent Lakeflow expectation
    `expect rule_id_native IS NOT NULL on violation drop row` runs
    on the silver_findings pipeline.
    """
    raw = [
        {
            "site": [
                {
                    "@name": "https://app.test",
                    "alerts": [
                        {
                            "pluginid": "10202",
                            "riskdesc": "Medium (Medium)",
                            "cweid": "200",
                            "instances": [
                                {"uri": "https://app.test/api"},
                            ],
                        },
                        {
                            "pluginid": "",
                            "riskdesc": "High (Medium)",
                            "instances": [{"uri": "https://app.test/y"}],
                        },
                        {
                            "pluginid": "10044",
                            "riskdesc": "Low (Low)",
                            "instances": [{"uri": ""}],
                        },
                    ],
                },
                {
                    "@name": "",
                    "@host": "",
                    "alerts": [
                        {
                            "pluginid": "10202",
                            "riskdesc": "Medium (Medium)",
                            "instances": [{"uri": "https://x/y"}],
                        }
                    ],
                },
            ]
        }
    ]
    rows = alerts_to_silver(spark, raw).collect()
    assert len(rows) == 1
    assert rows[0]["finding_id"] == "10202@https://app.test/api"


@pytest.mark.requirement("REQ-DQ")
def test_unmatched_target_passes_through_unchanged(spark: SparkSession) -> None:
    """REQ-DQ: per references/dast.md § "Target Silver tables", the
    deployments join is LEFT — unmatched targets pass through with
    application_id null so an inventory-gap report can surface them
    downstream. DO NOT drop rows; DO NOT raise.
    """
    raw = [_load_scan_report()]
    findings = alerts_to_silver(spark, raw)
    # Project a `target` column onto findings (the join key) — the
    # alerts_to_silver path stops at the silver_findings schema; the
    # join helper expects the caller to materialise `target`.
    from pyspark.sql import functions as F

    findings_with_target = findings.withColumn(
        "target", F.regexp_extract(F.col("url"), r"^(https?://[^/]+)", 1)
    )
    deployments = spark.createDataFrame(
        [],
        schema="target string, application_id string",
    )
    joined = apply_deployments_join(findings_with_target, deployments)
    rows = joined.collect()
    # All rows survive even though no deployment matches.
    assert len(rows) == 5
    assert {r["application_id"] for r in rows} == {None}


# ---------------------------------------------------------------------------
# REQ-DEDUP: dedup-key tuple
# ---------------------------------------------------------------------------


@pytest.mark.requirement("REQ-DEDUP")
def test_dedup_key_tuple_matches_mapping_yml() -> None:
    """REQ-DEDUP: the dedup key is the tuple (target, alert_id, uri_path)
    per the DAST category reference (references/dast.md § "Deduplication
    key") and mapping.yml.

    Two findings on the same site+plugin+URI produce identical dedup
    tuples; distinct components produce distinct tuples.
    """
    mapping = yaml.safe_load(_MAPPING_PATH.read_text())
    assert mapping["dedup_key"] == ["target", "alert_id", "uri_path"]

    key_a = dedup_key_for("https://app.test", "10202", "/api")
    key_b = dedup_key_for("https://app.test", "10202", "/api")
    key_c_diff_path = dedup_key_for("https://app.test", "10202", "/api/users/42")
    key_d_diff_plugin = dedup_key_for("https://app.test", "40012", "/api")
    key_e_diff_target = dedup_key_for("https://other.test", "10202", "/api")

    assert key_a == key_b
    assert key_a != key_c_diff_path
    assert key_a != key_d_diff_plugin
    assert key_a != key_e_diff_target
    assert key_a == ("https://app.test", "10202", "/api")


@pytest.mark.requirement("REQ-DEDUP")
def test_split_target_extracts_dedup_components() -> None:
    """REQ-DEDUP: the URI is split into (target, uri_path) for the dedup
    tuple. target = scheme+host+port; uri_path = path+query.
    """
    target, path = _split_target("https://app.test/api/users?id=42")
    assert target == "https://app.test"
    assert path == "/api/users?id=42"

    target_only, default_path = _split_target("https://app.test")
    assert target_only == "https://app.test"
    assert default_path == "/"


# ---------------------------------------------------------------------------
# REQ-ING-HWM: HWM shape declared in config.yml (cross-bound here so the
# config invariant is exercised even if test_ingest is skipped).
# ---------------------------------------------------------------------------


@pytest.mark.requirement("REQ-ING-HWM")
def test_hwm_kind_declared_in_config() -> None:
    """REQ-ING-HWM: config.yml declares hwm_kind explicitly; per
    references/dast.md the value MUST be one of {artefact_prefix, scan_id}.
    The MVP wires the artefact-prefix mode by default; the daemon path is
    layered via the trigger_routing block.
    """
    cfg = yaml.safe_load(_CONFIG_PATH.read_text())
    assert cfg["hwm_kind"] in ("artefact_prefix", "scan_id")
    if cfg["hwm_kind"] == "artefact_prefix":
        assert cfg["cicd_prefix"].startswith("cicd/")
    # Both paths MUST be discoverable from the config — the hybrid
    # invariant per §3 Quirks of the connector page.
    assert "scan_orchestration_mode" in cfg
    assert cfg["scan_orchestration_mode"] in ("scan_and_read", "read_only")
    assert "trigger_routing" in cfg
