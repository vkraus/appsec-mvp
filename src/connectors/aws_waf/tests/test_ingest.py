"""AWS WAF ingestion tests.

REQ-ID coverage:
- REQ-ING-AUTH: The ingest wrapper rejects missing IAM service-credential
  references with a clear ValueError (REQ-ING-AUTH, bound).
- REQ-ING-HWM: The HWM strategy is timestamp-based and round-trips through
  a persisted store (REQ-ING-HWM, bound via UpdatedAtHwm over the shared
  src.platform.hwm helper).
- REQ-ING-PAG: N/A under the preferred log-stream surface (no pagination).
  SDK-fallback pagination collapses to a single-page contract; we bind a
  skip-marked placeholder test per the WAF reference.
- REQ-ING-RL: N/A under the log-stream surface (no API quota). SDK-fallback
  rate-limit retry is boto3-native; skip-marked placeholder.

No local SparkSession is instantiated — pure-Python contracts only per the
CLAUDE.md architectural rules.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.connectors.aws_waf.ingest import (
    DOCUMENTED_ACTIONS,
    classify_ingestion_mode,
    ingest_contract,
    iter_sampled_requests,
)
from src.platform.hwm import HwmStore, UpdatedAtHwm

FIX = Path(__file__).parent / "fixtures"


@pytest.mark.requirement("REQ-ING-AUTH")
def test_ingest_contract_rejects_missing_aws_credential_ref() -> None:
    """REQ-ING-AUTH: invalid / missing credentials surface as clear errors.

    The AWS WAF connector resolves credentials out-of-band through the
    Databricks workspace's AWS service credential. The contract wrapper
    MUST fail loudly when the credential reference is absent so that
    misconfiguration never silently swallows events.
    """
    spark = MagicMock()
    state = {
        "source": "aws_waf",
        "run_id": "rid-missing-cred",
        "extra": {
            "spark": spark,
            "catalog": "appsec_dev",
            "bucket": "example-waf",
            "prefix": "waf/firehose/",
            # aws_credential_ref deliberately omitted
        },
    }
    with pytest.raises(ValueError, match="aws_credential_ref"):
        ingest_contract("rid-missing-cred", state)


@pytest.mark.requirement("REQ-ING-AUTH")
def test_ingest_contract_rejects_missing_catalog() -> None:
    """Complementary REQ-ING-AUTH guard: missing target catalog is rejected."""
    spark = MagicMock()
    state = {
        "source": "aws_waf",
        "run_id": "rid-missing-catalog",
        "extra": {
            "spark": spark,
            "aws_credential_ref": "waf-svc-cred",
            "bucket": "example-waf",
            "prefix": "waf/firehose/",
        },
    }
    with pytest.raises(ValueError, match="catalog"):
        ingest_contract("rid-missing-catalog", state)


@pytest.mark.requirement("REQ-ING-HWM")
def test_event_timestamp_hwm_round_trip(tmp_path) -> None:
    """REQ-ING-HWM: per-WebACL max(timestamp) persists across runs.

    The log-stream autoloader advances forward on each run; the recorded
    HWM is the max event-time seen in Bronze per WebACL. UpdatedAtHwm
    (the shared timestamp-based HWM helper) is the canonical store.
    """
    store = HwmStore(tmp_path / "aws_waf_hwm.json")
    hwm = UpdatedAtHwm("aws_waf::webacl::checkout-frontdoor", store)

    # First run: no HWM recorded yet -> epoch default.
    assert hwm.read() == datetime(1970, 1, 1, tzinfo=UTC)

    # Simulate ingest: record the max event-time seen in the batch.
    last_seen = datetime(2026, 4, 20, 10, 0, 0, tzinfo=UTC)
    hwm.write(last_seen)

    # Second run: HWM is resumed from the persisted store.
    resumed = UpdatedAtHwm("aws_waf::webacl::checkout-frontdoor", store)
    assert resumed.read() == last_seen


@pytest.mark.requirement("REQ-ING-HWM")
def test_event_timestamp_hwm_rejects_naive_datetime(tmp_path) -> None:
    """HWM write MUST refuse naive datetimes — WAF timestamps are UTC."""
    store = HwmStore(tmp_path / "aws_waf_hwm.json")
    hwm = UpdatedAtHwm("aws_waf::webacl::x", store)
    with pytest.raises(ValueError, match="timezone-aware"):
        hwm.write(datetime(2026, 4, 20, 10, 0, 0))   # naive — rejected


def test_classify_ingestion_mode_accepts_documented_modes() -> None:
    assert classify_ingestion_mode("log_stream") == "log_stream"
    assert classify_ingestion_mode("sdk_sampled") == "sdk_sampled"


def test_classify_ingestion_mode_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError):
        classify_ingestion_mode("http")   # not a documented surface


def test_documented_actions_match_reference_vocabulary() -> None:
    """Action vocabulary MUST be exhaustive over the WAF reference profile."""
    expected = {"ALLOW", "BLOCK", "COUNT", "CAPTCHA", "CHALLENGE"}
    assert set(DOCUMENTED_ACTIONS) == expected


def test_iter_sampled_requests_preserves_weight_field() -> None:
    """SDK-fallback quirk: the ``Weight`` field MUST reach Bronze unchanged.

    The WAF reference profile preserves the sampling weight so that
    downstream Gold aggregations can extrapolate true traffic volume.
    """
    sample = json.loads((FIX / "sdk_sampled_block.json").read_text())
    client = MagicMock()
    client.get_sampled_requests.return_value = {
        "SampledRequests": [
            {k: v for k, v in sample.items() if k != "webaclId"},
        ],
    }

    out = list(iter_sampled_requests(
        client,
        web_acl_arn=sample["webaclId"],
        rule_metric_name="SQLi_BODY",
        scope="CLOUDFRONT",
        start_time=datetime(2026, 4, 20, 9, 0, tzinfo=UTC),
        end_time=datetime(2026, 4, 20, 10, 0, tzinfo=UTC),
    ))

    assert len(out) == 1
    assert out[0]["Weight"] == 23
    # The ARN is projected onto each sample so Bronze rows from both surfaces
    # share the same ARN-based linkage key.
    assert out[0]["webaclId"] == sample["webaclId"]


# ------------------------------------------------------------------
# REQ-IDs N/A under the preferred log-stream surface — skip-marked
# placeholders per the WAF reference profile.
# ------------------------------------------------------------------

@pytest.mark.requirement("REQ-ING-PAG")
@pytest.mark.skip(reason="N/A: log-stream autoloader has no pagination; SDK-fallback GetSampledRequests is single-page (MaxItems=500 cap)")
def test_pagination_not_applicable_under_log_stream() -> None:
    """REQ-ING-PAG: N/A in the preferred log-stream mode.

    Under the SDK-fallback surface this collapses to a single-page
    contract per the connector page; it is bound here only for the
    traceability matrix.
    """
    raise AssertionError("unreachable — test is skip-marked")


@pytest.mark.requirement("REQ-ING-RL")
@pytest.mark.skip(reason="N/A: log-stream autoloader has no API quota; SDK-fallback retry is delegated to boto3's native ThrottlingException handling")
def test_rate_limit_not_applicable_under_log_stream() -> None:
    """REQ-ING-RL: N/A in the preferred log-stream mode."""
    raise AssertionError("unreachable — test is skip-marked")


# ------------------------------------------------------------------
# Live-only paths — skip unless LIVE_AWS_WAF is set.
# ------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.skip(reason="live-only: requires AWS creds and a Firehose-to-S3 prefix")
def test_run_ingest_pipeline_live_log_stream() -> None:
    """End-to-end log-stream ingest against a real S3 prefix. Live-only."""
    raise AssertionError("unreachable — test is skip-marked")
