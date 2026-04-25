"""Verify aws_waf.ingest and aws_waf.transform expose the section 2.4.1 contract."""
from __future__ import annotations

import inspect

import pytest


@pytest.mark.requirement("REQ-FW-CONTRACT")
def test_ingest_wrapper_has_contract_signature() -> None:
    from src.connectors.aws_waf import ingest as mod

    # The source-specific log-stream primitive retains its signature under
    # ``run_ingest_pipeline``; ``ingest_contract`` is the framework-contract
    # facade used by callers.
    sig = inspect.signature(mod.ingest_contract)
    params = list(sig.parameters)
    assert params == ["run_id", "state"], params


@pytest.mark.requirement("REQ-FW-CONTRACT")
def test_transform_wrapper_has_contract_signature() -> None:
    from src.connectors.aws_waf import transform as mod

    sig = inspect.signature(mod.transform)
    params = list(sig.parameters)
    assert params == ["bronze_df"], params


@pytest.mark.requirement("REQ-FW-BRONZE-ENVELOPE")
def test_run_ingest_pipeline_accepts_run_id_kwarg() -> None:
    """The envelope's ``_batch_id`` comes from ``run_id``. The contract wrapper
    must thread ``run_id`` through to ``run_ingest_pipeline`` as a keyword-only
    argument so the envelope and the ``BatchDescriptor`` agree on the run id.
    """
    from src.connectors.aws_waf import ingest as mod

    sig = inspect.signature(mod.run_ingest_pipeline)
    assert "run_id" in sig.parameters
    assert sig.parameters["run_id"].kind is inspect.Parameter.KEYWORD_ONLY
