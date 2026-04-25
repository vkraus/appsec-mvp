"""Tests for the Semgrep CLI / Docker-artefact ingest path.

REQ bindings per references/sast.md (§ "Applicable REQ-IDs", CLI-based SAST):

- REQ-ING-HWM : full-reload still carries an HWM in the form of the
  per-lane key encoded in the artefact path
  (``cicd/semgrep/<repo>/<sha>.{json,sarif}`` -> commit_sha,
  ``periodic/semgrep/<repo>/<ts>.{json,sarif}`` -> scan_start_timestamp).
- REQ-FW-CONTRACT : the framework contract
  ``ingest(run_id, state) -> BatchDescriptor`` is realised by
  ``ingest_contract``.

REQ-IDs N/A for CLI-based SAST (and therefore NOT bound here):

- REQ-ING-AUTH : Semgrep CLI has no API; auth is the artefact-bucket
  IAM's problem. The catalog matrix marks this N/A on the Semgrep row.
- REQ-ING-PAG  : each artefact is a single self-contained document — no
  pagination, no Link header, no cursor.
- REQ-ING-RL   : reads come from S3 (subject to S3's own quotas) — no
  per-client tool quota.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from src.connectors.semgrep import ingest as mod

FIX = Path(__file__).parent / "fixtures"


def _load(name: str):
    return json.loads((FIX / name).read_text())


@pytest.mark.requirement("REQ-FW-CONTRACT")
def test_ingest_contract_exposes_section_2_4_1_signature() -> None:
    """``ingest_contract`` must take ``(run_id, state)`` per thesis § 2.4.1."""
    sig = inspect.signature(mod.ingest_contract)
    params = list(sig.parameters)
    assert params == ["run_id", "state"], params


@pytest.mark.requirement("REQ-FW-BRONZE-ENVELOPE")
def test_run_ingest_pipeline_accepts_run_id_kwarg() -> None:
    """``run_id`` must be keyword-only so the bronze envelope's ``_batch_id``
    and the ``BatchDescriptor`` agree on the run identifier."""
    sig = inspect.signature(mod.run_ingest_pipeline)
    assert "run_id" in sig.parameters
    assert sig.parameters["run_id"].kind is inspect.Parameter.KEYWORD_ONLY


@pytest.mark.requirement("REQ-ING-HWM")
def test_parse_artefact_key_routes_cicd_and_periodic_lanes() -> None:
    """Per the connector page § "Quirks" — "HWM key differs by lane."
    cicd lane keys carry a commit SHA stem; periodic lane keys carry an
    ISO 8601 scan-start timestamp stem. The shape encodes the per-lane
    HWM so Bronze can recover it independently of the document body."""
    cases = _load("prefix_routing.json")["cases"]
    assert cases, "prefix_routing.json must contain at least one case"
    for case in cases:
        trigger_context, repository_id, hwm_value = mod.parse_artefact_key(case["key"])
        assert trigger_context == case["expected_trigger_context"], case["key"]
        assert repository_id == case["expected_repository_id"], case["key"]
        assert hwm_value == case["expected_hwm_value"], case["key"]


@pytest.mark.requirement("REQ-ING-HWM")
def test_detect_trigger_context_distinguishes_two_prefixes() -> None:
    """The trigger_context column in bronze_semgrep.findings is derived
    purely from the S3 prefix (per connector page § "Quirks"). Both
    prefixes route to the same Bronze table; only the discriminator
    differs."""
    assert mod.detect_trigger_context("cicd/semgrep/repo-a/abc.json") == "cicd"
    assert mod.detect_trigger_context("periodic/semgrep/repo-a/20260420T100000Z.sarif") == "periodic"


@pytest.mark.requirement("REQ-ING-HWM")
def test_detect_trigger_context_rejects_unknown_prefix() -> None:
    """Unknown prefixes must fail loudly so under-configured Auto Loader
    paths surface the misconfiguration rather than silently mis-tagging
    rows."""
    with pytest.raises(ValueError, match="unrecognised Semgrep artefact key"):
        mod.detect_trigger_context("other/semgrep/repo-a/abc.json")
    with pytest.raises(ValueError, match="unrecognised Semgrep artefact key"):
        mod.detect_trigger_context("")


@pytest.mark.requirement("REQ-ING-HWM")
def test_parse_artefact_key_rejects_shallow_key() -> None:
    """Keys that don't have the ``<lane>/semgrep/<repo>/<stem>.<ext>``
    shape must raise rather than fall through with partial values."""
    with pytest.raises(ValueError, match="unrecognised Semgrep artefact key"):
        mod.parse_artefact_key("cicd/semgrep/abc.json")
    with pytest.raises(ValueError, match="unrecognised Semgrep artefact"):
        mod.parse_artefact_key("cicd/semgrep/repo-a/abc.txt")


@pytest.mark.requirement("REQ-ING-HWM")
def test_detect_format_dispatches_by_extension() -> None:
    """Both `--json` and `--sarif` artefacts coexist. Routing is by
    extension (per connector page § "Quirks" — "JSON and SARIF
    coexist")."""
    cases = _load("prefix_routing.json")["cases"]
    for case in cases:
        assert mod.detect_format(case["key"]) == case["expected_format"], case["key"]


def test_ingest_contract_raises_without_extra_config() -> None:
    """Missing ``extra.spark`` / ``extra.bucket_uri`` / ``extra.catalog`` must
    fail loudly so an under-configured DAB job does not silently no-op."""
    with pytest.raises(ValueError, match="semgrep.ingest_contract requires"):
        mod.ingest_contract("run-1", {"source": "semgrep", "run_id": "run-1"})


# REQ-ING-AUTH / REQ-ING-PAG / REQ-ING-RL are N/A for the CLI-artefact
# path per references/sast.md § "Applicable REQ-IDs" (CLI-based SAST).
# Record the non-applicability via a skipped test so the traceability
# matrix shows the deliberate N/A rather than a silent gap. The catalog
# matrix at mkdocs/docs/platform/reference/catalog.md is the source of
# truth for these markers on the Semgrep row.
@pytest.mark.skip(reason="N/A for CLI-artefact SAST scanners (references/sast.md § Applicable REQ-IDs; catalog.md Semgrep row)")
@pytest.mark.requirement("REQ-ING-AUTH")
def test_req_ing_auth_na_for_cli_scanner() -> None:  # pragma: no cover - documentation marker
    pass


@pytest.mark.skip(reason="N/A for CLI-artefact SAST scanners (references/sast.md § Applicable REQ-IDs; catalog.md Semgrep row)")
@pytest.mark.requirement("REQ-ING-PAG")
def test_req_ing_pag_na_for_cli_scanner() -> None:  # pragma: no cover - documentation marker
    pass


@pytest.mark.skip(reason="N/A for CLI-artefact SAST scanners (references/sast.md § Applicable REQ-IDs; catalog.md Semgrep row)")
@pytest.mark.requirement("REQ-ING-RL")
def test_req_ing_rl_na_for_cli_scanner() -> None:  # pragma: no cover - documentation marker
    pass
