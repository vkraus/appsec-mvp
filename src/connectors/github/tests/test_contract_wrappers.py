"""Verify github.ingest and github.transform expose the section 2.4.1 contract."""
from __future__ import annotations

import inspect

import pytest


@pytest.mark.requirement("REQ-FW-CONTRACT")
def test_ingest_wrapper_has_contract_signature() -> None:
    from src.connectors.github import ingest as mod

    sig = inspect.signature(mod.ingest)
    params = list(sig.parameters)
    assert params == ["run_id", "state"], params


@pytest.mark.requirement("REQ-FW-CONTRACT")
def test_transform_wrapper_has_contract_signature() -> None:
    from src.connectors.github import transform as mod

    sig = inspect.signature(mod.transform)
    params = list(sig.parameters)
    assert params == ["bronze_df"], params
