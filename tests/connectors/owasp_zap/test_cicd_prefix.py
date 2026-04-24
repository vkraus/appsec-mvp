"""ZAP connector classifies CI/CD-step artifacts distinctly from on-demand."""

import pytest

from src.connectors.owasp_zap.ingest import classify_source


@pytest.mark.parametrize("path, expected", [
    ("s3://bucket/cicd/zap/vkraus/juiceshop/abcdef.json", "cicd"),
    ("api://zap/JSON/alert/view/alerts/", "on_demand"),
])
def test_classify_source(path, expected):
    assert classify_source(path) == expected
