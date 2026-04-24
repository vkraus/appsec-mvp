"""Semgrep reader classifies S3 keys into trigger_context values."""

import pytest

from src.connectors.semgrep.ingest import classify_prefix


@pytest.mark.parametrize("s3_key, expected", [
    ("periodic/semgrep/vkraus_seed-python-a/20260421T000000Z.json", "periodic"),
    ("cicd/semgrep/vkraus/juiceshop/abcdef1234.json", "cicd"),
])
def test_classify_prefix(s3_key, expected):
    assert classify_prefix(s3_key) == expected


def test_classify_prefix_rejects_unknown():
    with pytest.raises(ValueError, match="unrecognised prefix"):
        classify_prefix("random/other/key.json")
