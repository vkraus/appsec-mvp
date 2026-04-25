"""Verify semgrep.ingest and semgrep.transform expose the section 2.4.1 contract."""
from __future__ import annotations

import inspect

import pytest


@pytest.mark.requirement("REQ-FW-CONTRACT")
def test_ingest_wrapper_has_contract_signature() -> None:
    from src.connectors.semgrep import ingest as mod

    # The artifact-path ingest function retains its source-specific signature
    # under a new name (``run_ingest_pipeline``). The contract wrapper
    # ``ingest_contract`` is what callers use. Renamed to avoid shadowing.
    sig = inspect.signature(mod.ingest_contract)
    params = list(sig.parameters)
    assert params == ["run_id", "state"], params


@pytest.mark.requirement("REQ-FW-CONTRACT")
def test_transform_wrapper_has_contract_signature() -> None:
    from src.connectors.semgrep import transform as mod

    sig = inspect.signature(mod.transform)
    params = list(sig.parameters)
    assert params == ["bronze_df"], params


@pytest.mark.requirement("REQ-FW-BRONZE-ENVELOPE")
def test_run_ingest_pipeline_accepts_run_id_kwarg() -> None:
    """The envelope's ``_batch_id`` comes from ``run_id``. The contract wrapper
    must thread ``run_id`` through to ``run_ingest_pipeline`` as a keyword-only
    argument so the envelope and the ``BatchDescriptor`` agree on the run id.
    """
    from src.connectors.semgrep import ingest as mod

    sig = inspect.signature(mod.run_ingest_pipeline)
    assert "run_id" in sig.parameters
    assert sig.parameters["run_id"].kind is inspect.Parameter.KEYWORD_ONLY
