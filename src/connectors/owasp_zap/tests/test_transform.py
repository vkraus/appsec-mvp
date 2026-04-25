"""OWASP ZAP bronze-to-silver transform tests.

Binds REQ-ING-HWM, REQ-TRF-MAP, REQ-TRF-SEV, REQ-TRF-STS, REQ-TRF-TS,
REQ-DQ, REQ-DEDUP from the requirement catalog
(``mkdocs/docs/platform/reference/catalog.md``).

Tests that exercise the framework's silver schema use a local Spark
session, matching the established pattern in
``src/connectors/sonarqube/tests/test_transform.py``. Pure-logic tests
(severity/status lookup, dedup-key tuple, cwe normalization) run
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
    alerts_to_silver,
    dedup_key_for,
)
from src.platform.config import (
    ConnectorConfig,  # noqa: F401  (imported for symmetry; not used here)
    SeverityMap,
    StatusMap,
    load_yaml,
)
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


# --- REQ-ING-HWM: HWM-shape declared in config.yml --------------------------


@pytest.mark.requirement("REQ-ING-HWM")
def test_hwm_kind_artefact_prefix() -> None:
    """REQ-ING-HWM: ZAP's CI/CD-step path keys on the object-storage
    prefix, not a server-side ``updated_at`` column. ``config.yml``
    declares ``hwm_kind: artefact_prefix`` (the on-demand path keys on
    the numeric ``scanId`` per target). Both shapes are valid for ZAP
    and are documented in the connector page.
    """
    cfg = yaml.safe_load(_CONFIG_PATH.read_text())
    assert cfg["hwm_kind"] in ("artefact_prefix", "scan_id")
    # The MVP wires the artefact-prefix mode; verify the prefix is set.
    if cfg["hwm_kind"] == "artefact_prefix":
        assert cfg["cicd_prefix"].startswith("cicd/")


# --- REQ-TRF-MAP: schema mapping --------------------------------------------


@pytest.mark.requirement("REQ-TRF-MAP")
def test_alert_mapping(spark: SparkSession) -> None:
    """REQ-TRF-MAP: ZAP scan-report fields project onto silver_findings
    with correct types, values, and DAST-shape null handling
    (``file_path`` / ``start_line`` / ``cve_id`` / ``repository_id``
    null; ``url`` carries the per-instance URI; ``rule_id_native``
    carries the plugin id).
    """
    raw = [_load_scan_report()]
    rows = alerts_to_silver(spark, raw).collect()
    by_id = {r["finding_id"]: r for r in rows}

    # 4 alerts; one alert has 2 instances → 5 rows total.
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
    # cweid="79" → projected verbatim (CWE-prefixing is enrichment-side).
    assert row["cwe_id"] == "79"
    # trigger_context defaults to "cicd" for the MVP CI/CD-step path.
    assert row["trigger_context"] == "cicd"


@pytest.mark.requirement("REQ-TRF-MAP")
def test_finding_id_composition_per_mapping_yml(spark: SparkSession) -> None:
    """REQ-TRF-MAP: ``mapping.yml`` declares
    ``finding_id: pluginid + "@" + uri``. Two instances of the same
    alert at distinct URIs must produce distinct finding_ids.
    """
    raw = [_load_scan_report()]
    out = {r["finding_id"]: r for r in alerts_to_silver(spark, raw).collect()}

    assert "10202@https://app.test/api/users" in out
    assert "10202@https://app.test/api/users/42" in out
    # Same plugin, distinct URIs → distinct finding_ids.
    assert (
        out["10202@https://app.test/api/users"]["url"]
        != out["10202@https://app.test/api/users/42"]["url"]
    )


@pytest.mark.requirement("REQ-TRF-MAP")
def test_cweid_placeholder_collapses_to_null() -> None:
    """REQ-TRF-MAP: ZAP emits ``cweid="0"`` (and occasionally ``-1``)
    for findings with no CWE classification. Those values are
    placeholders and must collapse to NULL rather than appearing as
    a literal '0' CWE.
    """
    assert _normalize_cwe(None) is None
    assert _normalize_cwe("") is None
    assert _normalize_cwe("0") is None
    assert _normalize_cwe("-1") is None
    assert _normalize_cwe("79") == "79"
    assert _normalize_cwe(200) == "200"


# --- REQ-TRF-SEV: severity normalization ------------------------------------


@pytest.mark.requirement("REQ-TRF-SEV")
def test_severity_normalization_all_four_levels() -> None:
    """REQ-TRF-SEV: all four ZAP risk levels normalize to canonical
    severity. ZAP has no direct ``critical`` equivalent; promotion is
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
    ``info`` default (per ``src.platform.silver.normalize_severity``)
    rather than crashing or masquerading as a known level.
    """
    sev = load_yaml(SeverityMap, _SEV_PATH)
    assert normalize_severity("Catastrophic", sev) == "info"


@pytest.mark.requirement("REQ-TRF-SEV")
def test_riskdesc_split_extracts_risk_token() -> None:
    """REQ-TRF-SEV: ZAP's JSON report carries the four-level risk inside
    ``riskdesc`` as ``"<Risk> (<Confidence>)"``. The leading token is
    the risk level used for severity lookup.
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
    assert (
        by_id["10202@https://app.test/api/users"]["severity_canonical"] == "medium"
    )
    assert by_id["10038@https://app.test/"]["severity_canonical"] == "low"
    assert (
        by_id["10049@https://app.test/static/main.js"]["severity_canonical"]
        == "info"
    )


# --- REQ-TRF-STS: status normalization --------------------------------------


@pytest.mark.requirement("REQ-TRF-STS")
def test_status_always_open(spark: SparkSession) -> None:
    """REQ-TRF-STS: ZAP has no server-side lifecycle. Per status.yml,
    every finding lands as ``open``. The Bronze-to-Silver dedup
    reconstructs continuity across scans using the DAST dedup key
    ``(target, alert_id, uri_path)``.
    """
    raw = [_load_scan_report()]
    rows = alerts_to_silver(spark, raw).collect()
    assert {r["status_canonical"] for r in rows} == {"open"}


@pytest.mark.requirement("REQ-TRF-STS")
def test_status_lookup_default_open() -> None:
    """REQ-TRF-STS: any unrecognized status falls through to ``open``
    per ``src.platform.silver.normalize_status``. (ZAP only ever
    supplies "open" because status.yml is a single-entry map; this
    asserts the default contract.)
    """
    status = load_yaml(StatusMap, _STATUS_PATH)
    assert normalize_status("UNKNOWN_STATE", status) == "open"
    assert normalize_status("open", status) == "open"


# --- REQ-TRF-TS: timestamp normalization ------------------------------------


@pytest.mark.requirement("REQ-TRF-TS")
def test_first_seen_at_is_utc_aware(spark: SparkSession) -> None:
    """REQ-TRF-TS: ``first_seen_at`` and ``last_seen_at`` are emitted
    as timezone-aware UTC datetimes. The fixture's ``@generated``
    string ("Tue, 21 Apr 2026 10:00:00") has no offset and is treated
    as UTC at the Bronze layer.
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
    """REQ-TRF-TS: when ``@generated`` is absent the connector stamps
    a fallback timestamp (the run's wall-clock UTC). The fallback is
    accepted by callers that pass a deterministic ``fallback_now``.
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


# --- REQ-DQ: data-quality expectation ---------------------------------------


@pytest.mark.requirement("REQ-DQ")
def test_findings_expectation_quarantines_malformed(spark: SparkSession) -> None:
    """REQ-DQ: malformed records are dropped at the transform gate.
    A row missing ``pluginid``, missing the scanned site, or with an
    instance that has no ``uri`` cannot land in Silver: the synthetic
    ``finding_id`` (``pluginid@uri``) is non-nullable and the dedup
    tuple ``(target, alert_id, uri_path)`` requires all three.

    On Databricks, an equivalent Lakeflow expectation
    ``expect rule_id_native IS NOT NULL on violation drop row`` runs
    on the silver_findings pipeline.
    """
    raw = [
        {
            "site": [
                {
                    "@name": "https://app.test",
                    "alerts": [
                        {
                            # valid finding
                            "pluginid": "10202",
                            "riskdesc": "Medium (Medium)",
                            "cweid": "200",
                            "instances": [
                                {"uri": "https://app.test/api"},
                            ],
                        },
                        {
                            # malformed: no pluginid → drop
                            "pluginid": "",
                            "riskdesc": "High (Medium)",
                            "instances": [{"uri": "https://app.test/y"}],
                        },
                        {
                            # malformed: instance has no uri → drop
                            "pluginid": "10044",
                            "riskdesc": "Low (Low)",
                            "instances": [{"uri": ""}],
                        },
                    ],
                },
                {
                    # malformed: no @name/@host → drop entire site
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


# --- REQ-DEDUP: dedup-key tuple ---------------------------------------------


@pytest.mark.requirement("REQ-DEDUP")
def test_dedup_key_tuple_matches_mapping_yml() -> None:
    """REQ-DEDUP: the dedup key is the tuple
    ``(target, alert_id, uri_path)`` per the DAST category reference
    (``references/dast.md`` § "Deduplication key") and ``mapping.yml``.

    Two findings on the same site+plugin+URI produce identical dedup
    tuples; distinct URIs produce distinct tuples.
    """
    # Verify mapping.yml declares the same dedup key shape.
    mapping = yaml.safe_load(_MAPPING_PATH.read_text())
    assert mapping["dedup_key"] == ["target", "alert_id", "uri_path"]

    key_a = dedup_key_for("https://app.test", "10202", "https://app.test/api")
    key_b = dedup_key_for("https://app.test", "10202", "https://app.test/api")
    key_c_diff_uri = dedup_key_for(
        "https://app.test", "10202", "https://app.test/api/users/42"
    )
    key_d_diff_plugin = dedup_key_for(
        "https://app.test", "40012", "https://app.test/api"
    )
    key_e_diff_target = dedup_key_for(
        "https://other.test", "10202", "https://app.test/api"
    )

    assert key_a == key_b                 # linked → same dedup tuple
    assert key_a != key_c_diff_uri        # distinct URI → distinct tuple
    assert key_a != key_d_diff_plugin     # distinct plugin → distinct tuple
    assert key_a != key_e_diff_target     # distinct target → distinct tuple
    assert key_a == ("https://app.test", "10202", "https://app.test/api")
