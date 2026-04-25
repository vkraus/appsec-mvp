"""Tests for the Semgrep Bronze→Silver transform.

REQ bindings per references/sast.md (§ "Applicable REQ-IDs", CLI-based SAST):

- REQ-TRF-MAP : declarative mapping in mapping.yml is honoured — every
  consumed JSON / SARIF field lands in the expected Silver column. Both
  artefact flavours are exercised because the connector accepts both.
- REQ-TRF-SEV : severity vocabularies (`ERROR/WARNING/INFO` for `--json`;
  `error/warning/note/none` for SARIF) map to the canonical four-level
  model via the lookup. Unknown values fall through to ``medium``.
- REQ-TRF-STS : status has no source vocabulary — literal ``open`` is
  stamped on every row (degraded form of REQ-TRF-STS per the connector
  page § "Enumerations"). transform.py MUST NOT include status-
  transition logic.
- REQ-TRF-TS  : ``source_timestamp`` is preserved when present (Semgrep
  `--json` output does not carry one — the artefact filename's commit-SHA
  / scan-start-ts is the time anchor and is tracked at the lane level via
  the per-lane HWM, NOT at the per-record level).
- REQ-DQ      : records with missing optional metadata (``extra.metadata``,
  ``locations[]`` with no region) still produce well-formed Silver rows
  rather than raising.
- REQ-DEDUP   : the dedup key is exactly
  ``(repository_id, file_path, rule_id)`` per references/sast.md.

REQ-IDs N/A for CLI-based SAST (and therefore NOT bound here):

- REQ-ING-AUTH, REQ-ING-PAG, REQ-ING-RL — see test_ingest.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.connectors.semgrep import transform as tfm

FIX = Path(__file__).parent / "fixtures"


def _load(name: str):
    return (FIX / name).read_text()


def _load_json(name: str):
    return json.loads(_load(name))


# --------------------------------------------------------------------------- #
# REQ-TRF-MAP — declarative mapping (JSON + SARIF)
# --------------------------------------------------------------------------- #


@pytest.mark.requirement("REQ-TRF-MAP")
def test_record_to_silver_json_projects_every_consumed_field() -> None:
    """Per connector page § "Resource schema excerpt" — `--json` fields
    `check_id`, `path`, `start.line`, `extra.message`, `extra.severity`,
    `extra.metadata.cwe[0]` must land in the expected Silver columns."""
    doc = _load_json("cicd_scan.json")
    rows = tfm.transform_artefact(
        "json",
        doc,
        repository_id="acme-payments-api",
        trigger_context="cicd",
    )
    assert len(rows) == 3

    error_row = rows[0]
    assert error_row["tool_source"] == "semgrep"
    assert error_row["category"] == "sast"
    assert error_row["rule_id_native"] == (
        "python.lang.security.audit.dangerous-subprocess-use.dangerous-subprocess-use"
    )
    assert error_row["rule_id"] == error_row["rule_id_native"]
    assert error_row["repository_id"] == "acme-payments-api"
    assert error_row["file_path"] == "src/api/runner.py"
    assert error_row["start_line"] == 42
    assert error_row["start_column"] == 5
    assert error_row["end_line"] == 42
    assert error_row["end_column"] == 60
    assert error_row["cwe_id"] == "CWE-78"
    assert "shell=True" in (error_row["message"] or "")
    assert error_row["trigger_context"] == "cicd"


@pytest.mark.requirement("REQ-TRF-MAP")
def test_sarif_results_to_silver_projects_every_consumed_field() -> None:
    """Per connector page § "Resource schema excerpt" — SARIF fields
    `runs[].results[].ruleId`, `level`, `message.text`,
    `locations[].physicalLocation.artifactLocation.uri`,
    `locations[].physicalLocation.region.startLine`, and the rule's
    `properties.tags` for CWE extraction must land in Silver."""
    doc = _load_json("periodic_scan.sarif")
    rows = tfm.transform_artefact(
        "sarif",
        doc,
        repository_id="acme-payments-api",
        trigger_context="periodic",
    )
    assert len(rows) == 3

    error_row = next(r for r in rows if r["native_severity"] == "error")
    assert error_row["tool_source"] == "semgrep"
    assert error_row["category"] == "sast"
    assert error_row["rule_id"] == (
        "python.lang.security.audit.dangerous-subprocess-use.dangerous-subprocess-use"
    )
    assert error_row["repository_id"] == "acme-payments-api"
    assert error_row["file_path"] == "src/api/runner.py"
    assert error_row["start_line"] == 42
    assert error_row["start_column"] == 5
    assert error_row["cwe_id"] == "CWE-78"
    assert error_row["trigger_context"] == "periodic"

    # `cwe:1004` (alternative tag form) must also resolve.
    cookie_row = next(r for r in rows if r["rule_id"].endswith("express-cookie-session-no-httponly"))
    assert cookie_row["cwe_id"] == "CWE-1004"


@pytest.mark.requirement("REQ-TRF-MAP")
def test_transform_artefact_rejects_unknown_format() -> None:
    """Routing by file extension is mandatory; unknown formats must fail
    loudly rather than silently dropping rows."""
    with pytest.raises(ValueError, match="unrecognised Semgrep artefact format"):
        tfm.transform_artefact(
            "xml",  # type: ignore[arg-type]
            {},
            repository_id="r",
            trigger_context="cicd",
        )


# --------------------------------------------------------------------------- #
# REQ-TRF-SEV — severity vocabularies (both JSON and SARIF)
# --------------------------------------------------------------------------- #


@pytest.mark.requirement("REQ-TRF-SEV")
@pytest.mark.parametrize(
    "native, expected",
    [
        ("ERROR", "high"),
        ("WARNING", "medium"),
        ("INFO", "low"),
    ],
)
def test_severity_lookup_json_vocabulary(native: str, expected: str) -> None:
    """Per connector page § "Enumerations" (JSON flavour): ERROR→high,
    WARNING→medium, INFO→low. Semgrep does NOT emit a value mapping to
    `critical`."""
    assert tfm.lookup_severity_json(native) == expected


@pytest.mark.requirement("REQ-TRF-SEV")
@pytest.mark.parametrize(
    "native, expected",
    [
        ("error", "high"),
        ("warning", "medium"),
        ("note", "low"),
        ("none", "low"),
    ],
)
def test_severity_lookup_sarif_vocabulary(native: str, expected: str) -> None:
    """Per connector page § "Enumerations" (SARIF flavour): error→high,
    warning→medium, note→low, none→low. Both vocabularies must be
    present in the lookup table because the same connector ingests both
    artefact flavours."""
    assert tfm.lookup_severity_sarif(native) == expected


@pytest.mark.requirement("REQ-TRF-SEV")
def test_severity_lookup_unknown_falls_through_to_medium() -> None:
    """Per references/sast.md § "Default severity" — unknown values fall
    through to ``medium`` with a data-quality warning."""
    assert tfm.lookup_severity_json("MYSTERY") == "medium"
    assert tfm.lookup_severity_sarif("emergency") == "medium"
    assert tfm.lookup_severity_json(None) == "medium"
    assert tfm.lookup_severity_sarif(None) == "medium"


@pytest.mark.requirement("REQ-TRF-SEV")
def test_mixed_severity_fixture_round_trips_to_canonical_levels() -> None:
    """Exhaustive coverage of the JSON severity vocabulary across one
    artefact, including an unmapped value that must default to medium."""
    doc = _load_json("mixed_severity.json")
    rows = tfm.transform_artefact(
        "json",
        doc,
        repository_id="repo-a",
        trigger_context="cicd",
    )
    by_rule = {r["rule_id"]: r["severity_canonical"] for r in rows[:4]}
    assert by_rule == {
        "rule.error.example": "high",
        "rule.warning.example": "medium",
        "rule.info.example": "low",
        "rule.unknown.example": "medium",  # default fallthrough
    }


@pytest.mark.requirement("REQ-TRF-SEV")
def test_severity_yml_covers_both_vocabularies() -> None:
    """``src/connectors/semgrep/severity.yml`` must enumerate both the
    JSON (`ERROR/WARNING/INFO`) and SARIF (`error/warning/note/none`)
    vocabularies — the lookup is required to be exhaustive over the
    documented vocabulary per references/sast.md."""
    text = (Path(__file__).resolve().parents[1] / "severity.yml").read_text()
    for token in ("ERROR:", "WARNING:", "INFO:", "error:", "warning:", "note:", "none:", "default:"):
        assert token in text, f"severity.yml missing token: {token}"


# --------------------------------------------------------------------------- #
# REQ-TRF-STS — status (degraded form: literal `open`)
# --------------------------------------------------------------------------- #


@pytest.mark.requirement("REQ-TRF-STS")
def test_status_canonical_is_literal_open_for_every_row() -> None:
    """Per connector page § "Enumerations" — Semgrep CLI exposes no
    finding lifecycle. Every Silver row carries ``status_canonical='open'``
    by literal mapping; transform.py MUST NOT include status-transition
    logic."""
    json_rows = tfm.transform_artefact(
        "json",
        _load_json("cicd_scan.json"),
        repository_id="acme-payments-api",
        trigger_context="cicd",
    )
    sarif_rows = tfm.transform_artefact(
        "sarif",
        _load_json("periodic_scan.sarif"),
        repository_id="acme-payments-api",
        trigger_context="periodic",
    )
    assert json_rows and sarif_rows
    for row in json_rows + sarif_rows:
        assert row["status_canonical"] == "open"


@pytest.mark.requirement("REQ-TRF-STS")
def test_transform_py_has_no_status_transition_logic() -> None:
    """Defensive check — Semgrep emits no lifecycle. Status is a literal
    constant, not a lookup or transition. Searching the source for
    obvious lifecycle vocabulary that should NEVER appear in a CLI-SAST
    transform catches accidental drift."""
    src = (Path(__file__).resolve().parents[1] / "transform.py").read_text()
    forbidden = ("triaged", "resolved", "false_positive", "dismissed")
    for token in forbidden:
        assert token not in src.lower(), f"transform.py must not reference status vocabulary: {token}"


# --------------------------------------------------------------------------- #
# REQ-TRF-TS — source timestamp passthrough
# --------------------------------------------------------------------------- #


@pytest.mark.requirement("REQ-TRF-TS")
def test_source_timestamp_is_none_for_json_records() -> None:
    """Semgrep `--json` output does not carry a per-record timestamp.
    The artefact filename's commit-SHA (cicd) or scan-start-ts (periodic)
    is the time anchor; it is tracked at the lane level via the per-lane
    HWM, not on the Silver row. The Silver schema's
    ``first_seen_at`` / ``last_seen_at`` are populated downstream from
    the bronze envelope's ``_ingestion_timestamp``."""
    rows = tfm.transform_artefact(
        "json",
        _load_json("cicd_scan.json"),
        repository_id="acme-payments-api",
        trigger_context="cicd",
    )
    assert rows
    for row in rows:
        assert row["source_timestamp"] is None


@pytest.mark.requirement("REQ-TRF-TS")
def test_source_timestamp_is_none_for_sarif_records() -> None:
    """SARIF v2.1.0 results carry no per-result timestamp either; the
    same lane-level HWM model applies."""
    rows = tfm.transform_artefact(
        "sarif",
        _load_json("periodic_scan.sarif"),
        repository_id="acme-payments-api",
        trigger_context="periodic",
    )
    assert rows
    for row in rows:
        assert row["source_timestamp"] is None


# --------------------------------------------------------------------------- #
# REQ-DQ — graceful degradation
# --------------------------------------------------------------------------- #


@pytest.mark.requirement("REQ-DQ")
def test_record_without_metadata_still_produces_well_formed_row() -> None:
    """A `--json` result without ``extra.metadata`` (CWE/OWASP/category
    omitted) must still produce a Silver row with null ``cwe_id`` rather
    than raising. CWE extraction is opportunistic per connector page §
    "Quirks" ("CWE extraction is opportunistic")."""
    record = {
        "check_id": "rule.example",
        "path": "src/x.py",
        "start": {"line": 1, "col": 1},
        "end": {"line": 1, "col": 5},
        "extra": {"message": "hello", "severity": "WARNING"},
    }
    out = tfm.record_to_silver_json(
        record,
        repository_id="repo-a",
        trigger_context="cicd",
    )
    assert out["cwe_id"] is None
    assert out["severity_canonical"] == "medium"
    assert out["rule_id"] == "rule.example"


@pytest.mark.requirement("REQ-DQ")
def test_sarif_result_without_locations_produces_null_location_fields() -> None:
    """A SARIF result whose ``locations[]`` is empty must yield null
    ``file_path`` / ``start_line`` rather than raising. Data-quality
    degradation is acceptable; a crash is not."""
    sarif_doc = {
        "runs": [
            {
                "tool": {"driver": {"name": "semgrep", "rules": []}},
                "results": [
                    {
                        "ruleId": "rule.no.location",
                        "level": "warning",
                        "message": {"text": "no location attached"},
                        "locations": [],
                    }
                ],
            }
        ]
    }
    rows = tfm.sarif_results_to_silver(
        sarif_doc,
        repository_id="repo-a",
        trigger_context="periodic",
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["file_path"] is None
    assert row["start_line"] is None
    assert row["severity_canonical"] == "medium"
    assert row["rule_id"] == "rule.no.location"


@pytest.mark.requirement("REQ-DQ")
def test_transform_artefact_returns_empty_when_results_missing() -> None:
    """A document with no top-level ``results`` (JSON) or ``runs`` (SARIF)
    must yield zero Silver rows — neither raise nor invent data."""
    assert tfm.transform_artefact("json", {}, repository_id="r", trigger_context="cicd") == []
    assert tfm.transform_artefact("sarif", {}, repository_id="r", trigger_context="periodic") == []


# --------------------------------------------------------------------------- #
# REQ-DEDUP — dedup key tuple per references/sast.md
# --------------------------------------------------------------------------- #


@pytest.mark.requirement("REQ-DEDUP")
def test_dedup_key_is_three_tuple_per_sast_reference() -> None:
    """Canonical SAST dedup key per references/sast.md
    § "Deduplication key"."""
    assert tfm.DEDUP_KEY == ("repository_id", "file_path", "rule_id")


@pytest.mark.requirement("REQ-DEDUP")
def test_dedup_collapses_repeated_rule_at_same_path() -> None:
    """Re-emission of the same ``(repository_id, file_path, rule_id)``
    triple across runs must collapse to one Silver identity, even when
    the upstream artefact appears twice (Auto Loader re-read, periodic +
    cicd both touching the same finding)."""
    doc = _load_json("mixed_severity.json")
    rows = tfm.transform_artefact(
        "json",
        doc,
        repository_id="repo-a",
        trigger_context="cicd",
    )
    duplicate_rows = [r for r in rows if r["rule_id"] == "rule.duplicate.example"]
    assert len(duplicate_rows) == 2  # two raw records...
    keys = {tfm.dedup_key_for(r) for r in duplicate_rows}
    # ...but they share one dedup-key tuple.
    assert keys == {("repo-a", "src/file_a.py", "rule.duplicate.example")}


@pytest.mark.requirement("REQ-DEDUP")
def test_dedup_distinguishes_different_rules_at_same_path() -> None:
    """Different rule_id values at the same (repo, file) must NOT
    collapse — preserves audit trails per references/sast.md."""
    doc = _load_json("cicd_scan.json")
    rows = tfm.transform_artefact(
        "json",
        doc,
        repository_id="acme-payments-api",
        trigger_context="cicd",
    )
    # runner.py has two distinct rules (dangerous-subprocess and unused-import).
    runner_rows = [r for r in rows if r["file_path"] == "src/api/runner.py"]
    keys = {tfm.dedup_key_for(r) for r in runner_rows}
    assert len(keys) == 2


@pytest.mark.requirement("REQ-DEDUP")
def test_dedup_key_unifies_across_lanes_for_same_finding() -> None:
    """The dedup tuple is independent of ``trigger_context`` — a finding
    that appears in both the cicd lane and the periodic lane (same
    repository, file, rule) collapses to one Silver identity. This is
    the cross-lane idempotence guarantee per the connector page § 4.

    Without this guarantee, downstream rollups would double-count the
    same code-level issue once per lane."""
    json_doc = _load_json("cicd_scan.json")
    cicd_rows = tfm.transform_artefact(
        "json",
        json_doc,
        repository_id="acme-payments-api",
        trigger_context="cicd",
    )
    # Re-emit the same finding via the periodic lane.
    periodic_rows = tfm.transform_artefact(
        "json",
        json_doc,
        repository_id="acme-payments-api",
        trigger_context="periodic",
    )
    # Same dedup keys despite different trigger_contexts.
    cicd_keys = {tfm.dedup_key_for(r) for r in cicd_rows}
    periodic_keys = {tfm.dedup_key_for(r) for r in periodic_rows}
    assert cicd_keys == periodic_keys
