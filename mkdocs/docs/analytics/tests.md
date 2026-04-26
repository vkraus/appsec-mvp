# Tests

The Tests page is a **traceability index** into the `pytest` suites co-located under [`src/{platform,connectors/<source>}/tests/`](https://github.com/vkraus/appsec-mvp/tree/main/src). Tests themselves are not duplicated in this documentation. They live with the code. This page describes the conventions and links out to the sources.

## Marker convention

Every test that validates a requirement carries a `@pytest.mark.requirement("REQ-...")` marker:

```python
@pytest.mark.requirement("REQ-ING-PAG")
def test_pagination_no_duplicates_across_pages():
    ...
```

The marker string **SHALL** be one of the IDs in the [REQ catalog](../platform/reference/catalog.md). The `validate-implementation` skill enumerates markers when it runs the suite and populates the traceability matrix for each source.

## Suite layout

```
src/
├── platform/tests/            # Tests for the shared framework library
│   ├── test_bronze.py         # HTTP client, pagination, HWM
│   ├── test_severity.py       # Severity normalization (REQ-TRF-SEV)
│   ├── test_status.py         # Status normalization (REQ-TRF-STS)
│   └── test_dedup.py          # Deduplication (REQ-DEDUP)
└── connectors/
    ├── servicenow/tests/
    │   ├── test_ingest.py     # REQ-ING-AUTH, REQ-ING-PAG, REQ-ING-RL, REQ-ING-HWM
    │   ├── test_transform.py  # REQ-TRF-MAP, REQ-TRF-TS
    │   └── fixtures/          # JSON fixtures: {endpoint}_{scenario}.json
    ├── github/tests/
    └── ...
```

## Running the suite

```bash
# (run from repo root)
pytest                                     # full suite
pytest src/connectors/servicenow/tests/ -v # one connector
pytest -m 'requirement("REQ-ING-HWM")'     # all tests bound to a single REQ-ID
```

!!! warning "No local Spark"
    Tests that touch `SparkSession`, `createDataFrame`, or Silver schemas run against Databricks Connect or as Databricks jobs. Never against a local `local[*]` session. Pure Python logic (HTTP clients, config parsing, severity and status lookups, HWM math) runs locally without Spark. See the [project memory note on no local Spark](https://github.com/vkraus/appsec-mvp/blob/main/.claude/memory/feedback_no_local_spark.md) (if exposed in repo).

## Traceability flow

```mermaid
flowchart LR
    src[src/connectors/{source}/] --> tests[src/connectors/{source}/tests/]
    tests -->|@pytest.mark.requirement| markers[REQ-* markers]
    markers --> validate[validate-implementation skill]
    validate --> matrix[Requirement Catalog<br/>traceability matrix]
    validate --> fixlist[Fix list for failing REQs]
```

The [REQ catalog](../platform/reference/catalog.md) matrix is populated by the `validate-implementation` skill on each connector. Each cell holds the outcome of every bound marker (`✓` pass, `✗` fail, `-` no bound test, `N/A` REQ doesn't apply to the category for this source).

## Coverage by source

Traceability rows for each source live on the connector page for that source under [Connectors](../connectors/index.md) under the **Implementation report** subsection, and are aggregated in the [REQ catalog](../platform/reference/catalog.md) matrix.

## Fixtures

Test fixtures follow the convention `{endpoint}_{scenario}.json` and live under `src/connectors/{source}/tests/fixtures/`. Scenarios deliberately cover:

- Normal case (representative payload from official docs).
- Empty result set (pagination empty response).
- Multi-page result set (forces at least two HTTP calls to exercise `REQ-ING-PAG`).
- Rate limit response (HTTP 429 with `Retry-After` header to exercise `REQ-ING-RL`).
- Error response (HTTP 4xx or 5xx to exercise auth error paths and retry exhaustion).
- Edge values for severity and status columns (every documented source value plus one undocumented value to exercise `REQ-TRF-SEV` and `REQ-TRF-STS` fallthrough).

## Analytics-layer test patterns

The analytics tests under `src/analytics/tests/` and
`src/analytics/app/tests/` are not connector-style integration tests —
they exercise pure-Python aggregation helpers and route handlers. Three
patterns recur:

### Synthetic DataFrame fixtures (lists of dicts)

Each Gold notebook factors its aggregation logic into a pure-Python
`compute_*_rows(...)` helper that takes lists of dicts and returns a
list of dicts. The pytest under `src/analytics/tests/gold/` builds those
inputs inline (no fixtures on disk, no JSON files) and asserts on the
returned dicts. There is no Spark in the test path.

```python
def test_compute_posture_rows_typical_case():
    findings = [
        {"repository_id": "r1", "severity_canonical": "critical",
         "status_canonical": "open"},
        {"repository_id": "r1", "severity_canonical": "critical",
         "status_canonical": "resolved"},
    ]
    app_repo = [{"repository_id": "r1", "application_id": "APP-001"}]
    rules = []

    rows = compute_posture_rows(findings, app_repo, rules,
                                snapshot_date=date(2026, 4, 25))

    assert rows == [{
        "snapshot_date": date(2026, 4, 25),
        "application_id": "APP-001",
        "severity_canonical": "critical",
        "open_count": 1,
        "closed_count": 1,
    }]
```

Three cases per Gold notebook: typical case, empty input, and one
edge case specific to the metric (suppression match, ISO-week
boundary, unmapped repository, etc.).

### Spark-applied path is skip-marked

Per CLAUDE.md, the project does not run a local `SparkSession`. The
Spark wrapper functions in each Gold notebook (`_run_notebook`,
`_spark_main`, the apply_suppression_rules Column expression) are
exercised only on the Databricks job cluster. Tests that would need a
local Spark are absent — the pure-Python path is the contract under
test, and the Spark wrapper is a thin Column-based applicator over the
same logic.

### Mocked SQL + FastAPI TestClient for the App

The App's tests under `src/analytics/app/tests/` use
`unittest.mock.patch` against `databricks.sql.connect` (or against the
two query helpers in `queries.py`) to return canned rows, and
`fastapi.testclient.TestClient` to exercise the route handlers
end-to-end without a live workspace.

```python
from unittest.mock import patch
from fastapi.testclient import TestClient
from src.analytics.app.main import app

def test_get_score_returns_breakdown():
    canned = {"application_id": "APP-001", "score": 23,
              "severity_breakdown": {"critical": 2, "high": 1,
                                     "medium": 0, "low": 0},
              "snapshot_date": "2026-04-25"}
    with patch("src.analytics.app.queries.fetch_score", return_value=canned), \
         patch("src.analytics.app.queries.connect"):
        client = TestClient(app)
        resp = client.get("/v1/score?app_id=APP-001")
    assert resp.status_code == 200
    assert resp.json()["score"] == 23
```

### Live tests are skip-marked and excluded from CI

Tests that need a real Databricks workspace (a deployed App, populated
Online Tables, valid PAT) carry `@pytest.mark.skip` with a reason
string. They live alongside the unit tests so operators can flip them on
manually for end-to-end smoke tests, but CI does not execute them.

```python
import pytest

@pytest.mark.skip(reason="live: requires a deployed App + valid PAT")
def test_score_endpoint_against_live_workspace():
    ...
```

The convention is to gate live tests with `@pytest.mark.skip` rather
than environment-variable detection, so the skip is unconditional and
the operator opts in by editing the test source. This avoids
accidental-cost surprises in CI.
