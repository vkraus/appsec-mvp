"""Tests for the TruffleHog CLI-artefact ingest path.

REQ bindings per references/secrets.md (§ "Applicable REQ-IDs"):

- REQ-ING-HWM : full-reload still carries an HWM in the form of the commit
  SHA encoded in the artefact key (``trufflehog/<repo>/<commit>.jsonl``).
- REQ-FW-CONTRACT : the framework contract ``ingest(run_id, state) -> BatchDescriptor``
  is realised by ``ingest_contract``.

REQ-IDs N/A for CLI-based secret scanners (and therefore NOT bound here):

- REQ-ING-AUTH : TruffleHog has no API; auth is the CI/CD runner's problem.
- REQ-ING-PAG  : no pagination — line-delimited JSON stream.
- REQ-ING-RL   : no rate limit — CLI runs locally on the runner.
"""

from __future__ import annotations

import inspect

import pytest

from src.connectors.trufflehog import ingest as mod


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
@pytest.mark.parametrize(
    "key, expected",
    [
        (
            "trufflehog/acme-payments-api/a1b2c3d4e5f6a7b8c9d0.jsonl",
            ("acme-payments-api", "a1b2c3d4e5f6a7b8c9d0"),
        ),
        (
            "trufflehog/acme-loyalty-web/c3d4e5f6a7b8.json",
            ("acme-loyalty-web", "c3d4e5f6a7b8"),
        ),
    ],
)
def test_parse_artefact_key_extracts_repo_and_commit_sha(key, expected) -> None:
    """The HWM for TruffleHog is the commit SHA. It is encoded in the
    artefact key shape ``trufflehog/<repo>/<sha>.jsonl`` so Bronze can
    recover it independently of the JSON body."""
    assert mod.parse_artefact_key(key) == expected


@pytest.mark.requirement("REQ-ING-HWM")
def test_parse_artefact_key_rejects_unknown_prefix() -> None:
    with pytest.raises(ValueError, match="unrecognised TruffleHog artefact key"):
        mod.parse_artefact_key("other/acme/sha.jsonl")


@pytest.mark.requirement("REQ-ING-HWM")
def test_parse_artefact_key_rejects_shallow_key() -> None:
    with pytest.raises(ValueError, match="unrecognised TruffleHog artefact key"):
        mod.parse_artefact_key("trufflehog/acme.jsonl")


def test_ingest_contract_raises_without_extra_config() -> None:
    """Missing ``extra.spark`` / ``extra.volume_uri`` / ``extra.catalog`` must
    fail loudly so an under-configured DAB job does not silently no-op."""
    with pytest.raises(ValueError, match="trufflehog.ingest_contract requires"):
        mod.ingest_contract("run-1", {"source": "trufflehog", "run_id": "run-1"})


# REQ-ING-AUTH / REQ-ING-PAG / REQ-ING-RL are N/A for CLI-based secret
# scanners per references/secrets.md § "Applicable REQ-IDs". Record the
# non-applicability via a skipped test so the traceability matrix shows
# the deliberate N/A rather than a silent gap.
@pytest.mark.skip(
    reason="N/A for CLI-artefact secrets scanners (references/secrets.md § Applicable REQ-IDs)"
)
@pytest.mark.requirement("REQ-ING-AUTH")
def test_req_ing_auth_na_for_cli_scanner() -> None:  # pragma: no cover - documentation marker
    pass


@pytest.mark.skip(
    reason="N/A for CLI-artefact secrets scanners (references/secrets.md § Applicable REQ-IDs)"
)
@pytest.mark.requirement("REQ-ING-PAG")
def test_req_ing_pag_na_for_cli_scanner() -> None:  # pragma: no cover - documentation marker
    pass


@pytest.mark.skip(
    reason="N/A for CLI-artefact secrets scanners (references/secrets.md § Applicable REQ-IDs)"
)
@pytest.mark.requirement("REQ-ING-RL")
def test_req_ing_rl_na_for_cli_scanner() -> None:  # pragma: no cover - documentation marker
    pass
