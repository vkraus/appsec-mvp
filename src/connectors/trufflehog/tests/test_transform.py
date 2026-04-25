"""Tests for the TruffleHog Bronze→Silver transform.

REQ bindings per references/secrets.md (§ "Applicable REQ-IDs"):

- REQ-TRF-MAP : declarative mapping in mapping.yml is honoured — every
  consumed JSON field lands in the expected Silver column.
- REQ-TRF-SEV : severity is the hard-coded literal ``high`` (degraded form
  — no source field; no lookup at runtime).
- REQ-TRF-TS  : ``SourceMetadata.Data.Git.timestamp`` is preserved and
  carried into Silver on ``source_timestamp``.
- REQ-DQ      : records with missing ``SourceMetadata.Data.Git`` leaf still
  produce a well-formed Silver row (null location fields, ``validity_status``
  defaults to ``unknown``) rather than raising.
- REQ-DEDUP   : the dedup key is exactly
  ``(repository_id, commit_sha, secret_type, file_path)``.

REQ-TRF-STS is N/A for secrets (§ "Applicable REQ-IDs" — do NOT bind).
It is recorded via a skipped marker below to make the non-applicability
visible in the traceability matrix.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.connectors.trufflehog import transform as tfm
from src.connectors.trufflehog.ingest import derive_validity_status

FIX = Path(__file__).parent / "fixtures"


def _load(name: str):
    return json.loads((FIX / name).read_text())


@pytest.mark.requirement("REQ-TRF-MAP")
def test_record_to_silver_projects_every_consumed_field() -> None:
    raw = _load("git_verified.json")

    out = tfm.record_to_silver(raw)

    assert out["tool_source"] == "trufflehog"
    assert out["category"] == "secrets"
    assert out["rule_id_native"] == "AWS"
    assert out["secret_type"] == "AWS"  # DetectorName substitutes for rule_id
    assert out["repository_id"] == "acme/payments-api"
    assert out["commit_sha"] == "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
    assert out["file_path"] == "config/aws.env"
    assert out["start_line"] == 12
    assert out["redacted"] == "AKIA****************"


@pytest.mark.requirement("REQ-TRF-MAP")
def test_record_to_silver_drops_raw_and_rawv2() -> None:
    """``Raw`` and ``RawV2`` MUST NOT enter Silver. Mandatory, not configurable."""
    raw = _load("git_verified.json")

    out = tfm.record_to_silver(raw)

    assert "Raw" not in out
    assert "RawV2" not in out
    assert "raw" not in out
    assert "rawv2" not in out


@pytest.mark.requirement("REQ-TRF-MAP")
def test_dropped_fields_enumerates_raw_rawv2() -> None:
    assert set(tfm.DROPPED_FIELDS) == {"Raw", "RawV2"}


@pytest.mark.requirement("REQ-TRF-SEV")
def test_severity_is_hard_coded_high() -> None:
    """Every TruffleHog finding gets ``severity_canonical='high'`` by
    convention (references/secrets.md § Default severity). The severity
    lookup file is consulted only for per-deployment detector overrides,
    not on the default code path."""
    for fixture in (
        "git_verified.json",
        "git_unverified_no_error.json",
        "git_unverified_with_error.json",
        "git_missing_metadata.json",
    ):
        out = tfm.record_to_silver(_load(fixture))
        assert out["severity_canonical"] == "high", fixture


@pytest.mark.requirement("REQ-TRF-SEV")
def test_severity_lookup_file_is_a_stub_comment() -> None:
    """``src/connectors/trufflehog/severity.yml`` must exist (framework contract
    requires both lookup files per connector) and carry the override marker.
    It is NOT referenced by the default transform path."""
    path = Path(__file__).resolve().parents[1] / "severity.yml"
    text = path.read_text()
    assert "default high" in text
    # No severity keys — the file is a comment-only stub.
    for line in text.splitlines():
        stripped = line.strip()
        assert not stripped or stripped.startswith("#"), line


@pytest.mark.requirement("REQ-TRF-TS")
def test_source_timestamp_is_preserved_from_git_leaf() -> None:
    """``SourceMetadata.Data.Git.timestamp`` survives the transform so
    downstream can normalise to UTC in Spark."""
    out = tfm.record_to_silver(_load("git_verified.json"))

    assert out["source_timestamp"] == "2026-04-20T10:00:00Z"


@pytest.mark.requirement("REQ-TRF-TS")
def test_source_timestamp_none_when_leaf_missing() -> None:
    """Records without a Git leaf fall back to ``None`` rather than raising."""
    out = tfm.record_to_silver(_load("git_missing_metadata.json"))

    assert out["source_timestamp"] is None


@pytest.mark.requirement("REQ-DQ")
def test_missing_git_metadata_produces_well_formed_row() -> None:
    """A record without ``SourceMetadata.Data.Git`` must not blow up — the
    transform should emit a Silver row with null location fields and
    ``validity_status='unknown'`` (since ``Verified=false`` with empty error
    means ``inactive``). Data-quality degradation is acceptable; a crash is not."""
    raw = _load("git_missing_metadata.json")

    out = tfm.record_to_silver(raw)

    assert out["tool_source"] == "trufflehog"
    assert out["category"] == "secrets"
    assert out["severity_canonical"] == "high"
    assert out["repository_id"] is None
    assert out["commit_sha"] is None
    assert out["file_path"] is None
    assert out["start_line"] is None
    # Verified=false with empty VerificationError => inactive
    assert out["validity_status"] == "inactive"


@pytest.mark.requirement("REQ-DQ")
@pytest.mark.parametrize(
    "verified, verification_error, expected",
    [
        (True, "", "active"),
        (True, None, "active"),
        (False, "", "inactive"),
        (False, None, "inactive"),
        (False, "dial tcp: i/o timeout", "unknown"),
        (None, None, "unknown"),
        (None, "", "unknown"),
    ],
)
def test_validity_status_derivation_matches_connector_page(
    verified, verification_error, expected
) -> None:
    """Per connector page § Enumerations — ``validity_status`` is a function
    of ``Verified`` and ``VerificationError``. Conflating ``unknown`` with
    ``inactive`` must not happen."""
    assert derive_validity_status(verified, verification_error) == expected


@pytest.mark.requirement("REQ-DEDUP")
def test_dedup_key_is_four_tuple_per_secrets_reference() -> None:
    """Canonical secrets dedup key per references/secrets.md
    § "Deduplication key"."""
    assert tfm.DEDUP_KEY == (
        "repository_id",
        "commit_sha",
        "secret_type",
        "file_path",
    )


@pytest.mark.requirement("REQ-DEDUP")
def test_dedup_unifies_cicd_and_periodic_emission_of_same_secret() -> None:
    """Both CI/CD-step and periodic host-side scans emit records with the
    same ``(repository_id, commit_sha)``. On the four-tuple dedup key they
    must collapse to a single Silver identity."""
    records = _load("git_duplicate_across_scans.json")
    silver_rows = tfm.transform_records(records)

    keys = {tfm.dedup_key_for(r) for r in silver_rows}
    assert len(keys) == 1
    (key,) = keys
    assert key == (
        "acme/payments-api",
        "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
        "AWS",
        "config/aws.env",
    )


@pytest.mark.requirement("REQ-DEDUP")
def test_dedup_distinguishes_different_commits_of_same_secret() -> None:
    """The per-commit dedup policy preserves audit trails — the same
    detector in different commits is NOT collapsed."""
    a = _load("git_verified.json")
    b = _load("git_unverified_no_error.json")  # different commit, different detector

    rows = tfm.transform_records([a, b])
    keys = {tfm.dedup_key_for(r) for r in rows}
    assert len(keys) == 2


# REQ-TRF-STS is N/A for secrets sources. Record the non-applicability as a
# skipped marker for the traceability matrix.
@pytest.mark.skip(reason="N/A for secrets sources (references/secrets.md § Applicable REQ-IDs); transform.py MUST NOT include status-transition logic")
@pytest.mark.requirement("REQ-TRF-STS")
def test_req_trf_sts_na_for_secrets() -> None:  # pragma: no cover - documentation marker
    pass


def test_transform_py_has_no_status_transition_logic() -> None:
    """Secrets sources emit no lifecycle. The Silver ``status_canonical``
    column is a literal ``open`` constant — NOT a lookup or transition."""
    from src.connectors.trufflehog.transform import record_to_silver

    row = record_to_silver(_load("git_verified.json"))
    assert row["status_canonical"] == "open"
