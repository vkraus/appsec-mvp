"""Skeleton tests for SonarQube connector — verify the scaffolding imports."""

import pytest

from src.connectors.sonarqube import ingest as ingest_mod
from src.connectors.sonarqube import transform as transform_mod


def test_ingest_module_imports():
    assert hasattr(ingest_mod, "ingest")


def test_transform_module_imports():
    assert hasattr(transform_mod, "transform")


def test_ingest_raises_not_implemented():
    with pytest.raises(NotImplementedError, match="scaffolding only"):
        ingest_mod.ingest(run_id="test", state=None)  # type: ignore[arg-type]


def test_transform_raises_not_implemented():
    with pytest.raises(NotImplementedError, match="scaffolding only"):
        transform_mod.transform(None)  # type: ignore[arg-type]
