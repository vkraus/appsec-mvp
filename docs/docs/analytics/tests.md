# Tests

The Tests surface is a **traceability index** into the `pytest` suites that live in [`tests/`](https://github.com/vkraus/appsec-mvp/tree/main/tests). Tests themselves are not duplicated in this documentation — they live with the code — so this page describes the conventions and links out to the sources.

## Marker convention

Every test that validates a requirement carries a `@pytest.mark.requirement("REQ-...")` marker:

```python
@pytest.mark.requirement("REQ-ING-PAG")
def test_pagination_no_duplicates_across_pages():
    ...
```

The marker string **SHALL** be one of the IDs in the [REQ catalog](../platform/reference/catalog.md). The `validate-implementation` skill enumerates markers when it runs the suite and populates the per-source traceability matrix.

## Suite layout

```
tests/
├── common/                 # Tests for the shared framework library
│   ├── test_bronze.py      # HTTP client, pagination, HWM
│   ├── test_severity.py    # Severity normalization (REQ-TRF-SEV)
│   ├── test_status.py      # Status normalization (REQ-TRF-STS)
│   └── test_dedup.py       # Deduplication (REQ-DEDUP)
└── connectors/
    ├── servicenow/
    │   ├── test_ingest.py  # REQ-ING-AUTH, REQ-ING-PAG, REQ-ING-RL, REQ-ING-HWM
    │   ├── test_transform.py  # REQ-TRF-MAP, REQ-TRF-TS
    │   └── fixtures/       # JSON fixtures: {endpoint}_{scenario}.json
    ├── github/
    └── ...
```

## Running the suite

```bash
# (run from repo root)
pytest                                     # full suite
pytest tests/connectors/servicenow/ -v     # one connector
pytest -m 'requirement("REQ-ING-HWM")'     # all tests bound to a single REQ-ID
```

!!! warning "No local Spark"
    Tests that touch `SparkSession`, `createDataFrame`, or Silver schemas run against Databricks Connect or as Databricks jobs — never against a local `local[*]` session. Pure-Python logic (HTTP clients, config parsing, severity/status lookups, HWM math) runs locally without Spark. See the [project memory note on no local Spark](https://github.com/vkraus/appsec-mvp/blob/main/.claude/memory/feedback_no_local_spark.md) (if exposed in repo).

## Traceability flow

```mermaid
flowchart LR
    src[src/connectors/{source}/] --> tests[tests/connectors/{source}/]
    tests -->|@pytest.mark.requirement| markers[REQ-* markers]
    markers --> validate[validate-implementation skill]
    validate --> matrix[Requirement Catalog<br/>traceability matrix]
    validate --> fixlist[Fix list for failing REQs]
```

The [REQ catalog](../platform/reference/catalog.md) matrix is populated by the `validate-implementation` skill on each connector: each cell holds the outcome of every bound marker (`✓` pass, `✗` fail, `-` no bound test, `N/A` REQ doesn't apply to this source's category).

## Per-source coverage

Per-source traceability rows live on the per-source connector pages under [Connectors](../connectors/index.md) under each source's **Implementation report** subsection, and are aggregated in the [REQ catalog](../platform/reference/catalog.md) matrix.

## Fixtures

Test fixtures follow the convention `{endpoint}_{scenario}.json` and live under `tests/connectors/{source}/fixtures/`. Scenarios deliberately cover:

- Normal case (representative payload from official docs).
- Empty result set (pagination-empty response).
- Multi-page result set (forces at least two HTTP calls to exercise `REQ-ING-PAG`).
- Rate-limit response (HTTP 429 with `Retry-After` header to exercise `REQ-ING-RL`).
- Error response (HTTP 4xx/5xx to exercise auth error paths and retry exhaustion).
- Edge values for severity / status columns (every documented source value + one undocumented value to exercise `REQ-TRF-SEV` / `REQ-TRF-STS` fallthrough).
