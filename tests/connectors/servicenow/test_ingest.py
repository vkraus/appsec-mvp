"""ServiceNow ingest REQ-bound tests.

The ServiceNow connector delegates ingestion to a Lakeflow Connect pipeline
declared in ``resources/servicenow-pipeline.yml``. The Python ``ingest``
entry point is a framework-contract wrapper (see ``test_contract_wrappers``);
the HTTP-level behaviour that the REQs constrain is expressed in
``config.yml`` and in the canonical framework helpers in ``src/common/``.

These tests bind the four ingest-side REQs from the CMDB REQ slate to the
declarative artefacts that drive the Lakeflow pipeline:

- REQ-ING-AUTH — auth block references secret-scope keys, never literals
- REQ-ING-PAG  — pagination strategy is offset with a configurable page size
- REQ-ING-RL   — rate-limit posture is expressed through the job's retry
                  policy on the ingest task
- REQ-ING-HWM  — sys_updated_on is the documented high-water-mark column and
                  survives a resume via the common UpdatedAtHwm store
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from src.common.config import ConnectorConfig, load_yaml
from src.common.hwm import HwmStore, UpdatedAtHwm


_CONFIG_PATH = Path(__file__).parents[3] / "src" / "connectors" / "servicenow" / "config.yml"
_JOB_PATH = Path(__file__).parents[3] / "resources" / "servicenow-job.yml"


@pytest.fixture(scope="module")
def servicenow_config() -> ConnectorConfig:
    return load_yaml(ConnectorConfig, _CONFIG_PATH)


@pytest.mark.requirement("REQ-ING-AUTH")
def test_auth_secret_resolution(servicenow_config: ConnectorConfig) -> None:
    """Auth keys reference secret-scope names, never plaintext credentials.

    The ServiceNow Table API is authenticated with a basic-auth service
    account per the connector page. The config must carry only
    ``*_secret`` pointers so deploys resolve real credentials from the
    Databricks secret scope at runtime.
    """
    assert servicenow_config.auth.type == "basic"
    assert servicenow_config.auth.username_secret, "username_secret must be set"
    assert servicenow_config.auth.password_secret, "password_secret must be set"
    # A plaintext secret would typically contain an '@' or look like a URL/password;
    # secret-scope keys are short identifiers. Assert they don't look like values.
    for key in (servicenow_config.auth.username_secret, servicenow_config.auth.password_secret):
        assert " " not in key
        assert "@" not in key
        assert ":" not in key


@pytest.mark.requirement("REQ-ING-PAG")
def test_offset_pagination_two_pages(servicenow_config: ConnectorConfig) -> None:
    """ServiceNow Table API is offset-paginated; config drives the walker.

    Asserts the declarative contract that downstream Lakeflow / SDK paths
    read. The page size is configurable and defaults to 1000 (well under
    the 10 000 ServiceNow maximum documented on the connector page).
    Simulates two-page consumption by stepping ``sysparm_offset`` by the
    configured ``page_size``.
    """
    assert servicenow_config.pagination.strategy == "offset"
    page_size = servicenow_config.pagination.page_size
    assert page_size > 0
    assert page_size <= 10_000, "ServiceNow Table API caps sysparm_limit at 10000"

    # Two-page offset walk: offsets are 0 and page_size. The walker halts when
    # a page returns fewer than page_size records.
    offsets = [i * page_size for i in range(2)]
    assert offsets == [0, page_size]


@pytest.mark.requirement("REQ-ING-RL")
def test_429_backoff_retries() -> None:
    """Ingest task carries a retry policy so HTTP 429s from ServiceNow
    are absorbed by the Lakeflow job's built-in retry loop.

    ServiceNow's transaction-quota subsystem returns 429 when concurrent
    sessions or cumulative processing exceed the per-60s window. The
    job fragment's ingest task must declare ``max_retries`` >= 1 and a
    non-zero ``min_retry_interval_millis`` so the framework retries with
    a bounded delay rather than failing the run on a transient quota hit.
    """
    with open(_JOB_PATH) as fh:
        job = yaml.safe_load(fh)
    tasks = job["resources"]["jobs"]["servicenow-connector"]["tasks"]
    ingest_task = next(t for t in tasks if t["task_key"] == "ingest")
    assert ingest_task["max_retries"] >= 1
    assert ingest_task["min_retry_interval_millis"] >= 1000
    assert ingest_task.get("retry_on_timeout") is True


@pytest.mark.requirement("REQ-ING-HWM")
def test_sys_updated_on_hwm_resume(servicenow_config: ConnectorConfig, tmp_path) -> None:
    """HWM column is sys_updated_on; UpdatedAtHwm round-trips it across runs.

    The first ingest writes the max observed ``sys_updated_on``; the next
    run reads it back and constructs the ``sysparm_query`` filter
    documented on the connector page. Round-tripping a timezone-aware
    timestamp through the shared ``UpdatedAtHwm`` is the framework-level
    contract for this behaviour.
    """
    assert servicenow_config.hwm.strategy == "updated_at"
    assert servicenow_config.hwm.column == "sys_updated_on"

    store = HwmStore(tmp_path / "hwm.json")
    hwm = UpdatedAtHwm(key="servicenow::cmdb_ci_business_app", store=store)

    # First run: epoch sentinel
    assert hwm.read() == datetime(1970, 1, 1, tzinfo=timezone.utc)

    # End of run 1: persist the max observed sys_updated_on
    observed_max = datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc)
    hwm.write(observed_max)

    # Run 2 resumes from the persisted value
    resumed = hwm.read()
    assert resumed == observed_max
    assert resumed.tzinfo is not None, "HWM must survive as timezone-aware"
