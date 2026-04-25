"""Bronze-to-silver transform for Semgrep.

Realises the declarative mapping at ``mapping.yml`` as pure Python so unit
tests exercise the normalisation rules without a Spark session. The
Databricks entry point in the DAB job wraps this with a Spark DataFrame
applicator.

Two artefact flavours coexist (per connector page section "Quirks" -- "JSON and
SARIF coexist"); the transform routes by file extension:

    *.json  -> Semgrep-native (semgrep.dev/docs/semgrep-appsec-platform/json-and-sarif)
    *.sarif -> SARIF v2.1.0  (docs.oasis-open.org/sarif/sarif/v2.1.0)

Dedup key per references/sast.md section "Deduplication key":

    (repository_id, file_path, rule_id)

Both lanes (cicd via commit SHA, periodic via scan-start timestamp) emit
records keyed by the same triple; the dedup key enforces idempotence
across re-reads.

Invariants:

- severity is a lookup on the source field (NOT a literal) -- see
  ``severity.yml``. Both vocabularies must be present because the same
  connector ingests both flavours. Default for unknown values is
  ``medium`` per references/sast.md section "Default severity"; the
  default is configured declaratively via the YAML's reserved ``default``
  key (NOT hard-coded in this module).
- status has no source vocabulary. The literal ``open`` is the only
  permitted canonical value; the lookup is routed through the platform
  applicator with ``status.yml`` as input so the framework's status-
  normalisation contract holds. transform.py MUST NOT include status-
  transition logic. REQ-TRF-STS applies in degraded form (single literal
  mapping) per the page section "Enumerations" (no status vocabulary).
- ``trigger_context`` is derived from the artefact's S3 prefix
  ('periodic' | 'cicd'), NOT from a payload field.
- ``repository_id`` is derived from the artefact's S3 key
  ('<lane>/semgrep/<repo>/<stem>.<ext>'), NOT from a payload field.
- ``cwe_id`` extraction is opportunistic -- null when the rule omits the
  CWE tag (per page section "Quirks" -- "CWE extraction is opportunistic").

The severity / status mappings are loaded once at module import via the
canonical platform helpers (``src.platform.config.load_yaml`` against
``SeverityMap`` / ``StatusMap``) and applied via the canonical applicators
``src.platform.silver.normalize_severity`` / ``normalize_status`` -- the
same code path the github and owasp_zap connectors use. There are no
inline Python lookup dicts: the YAML files are the single source of
truth.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

from src.platform.config import SeverityMap, StatusMap, load_yaml
from src.platform.silver import normalize_severity, normalize_status

# Dedup key per references/sast.md section "Deduplication key".
DEDUP_KEY: tuple[str, ...] = ("repository_id", "file_path", "rule_id")

_CONNECTOR_DIR = Path(__file__).parent
_SEVERITY_PATH = _CONNECTOR_DIR / "severity.yml"
_STATUS_PATH = _CONNECTOR_DIR / "status.yml"

# Load YAML lookups once at import. The same maps drive the JSON-flavour
# (uppercase keys: ERROR/WARNING/INFO) and SARIF-flavour (lowercase keys:
# error/warning/note/none) inputs -- the two vocabularies are distinct in
# case so they coexist in a single flat map without collision.
_SEVERITY_MAP: SeverityMap = load_yaml(SeverityMap, _SEVERITY_PATH)
_STATUS_MAP: StatusMap = load_yaml(StatusMap, _STATUS_PATH)

# Reserved YAML key carrying the configurable default for unknown native
# values, per references/sast.md section "Default severity". Falling back
# to "medium" if the YAML omits it preserves the documented contract for
# Semgrep specifically (the platform applicator's own unknown-fallthrough
# is "info", which is too low for SAST).
_SEVERITY_DEFAULT: str = _SEVERITY_MAP.root.get("default", "medium")
_STATUS_DEFAULT: str = _STATUS_MAP.root.get("default", "open")


def _severity_lookup(value: str | None) -> str:
    """Apply the YAML severity map with the YAML-declared default.

    Routes through ``src.platform.silver.normalize_severity`` so the
    framework-canonical applicator owns the lookup semantics; the
    Semgrep-specific "unknown -> medium" default (vs. the platform's
    own "unknown -> info" fallthrough) is layered on top by checking
    whether the native value is a recognised key. Both vocabularies
    (JSON uppercase, SARIF lowercase) live in the same map; the case
    distinction prevents key collisions.
    """
    if value is None or value not in _SEVERITY_MAP.root:
        return _SEVERITY_DEFAULT
    return normalize_severity(value, _SEVERITY_MAP)


def lookup_severity_json(value: str | None) -> str:
    """Map a Semgrep `--json` severity value to the canonical four-level model.

    Per references/sast.md section "Default severity": unknown values fall
    through to ``medium``. The connector page section "Enumerations" notes
    Semgrep does not natively emit a value mapping to ``critical``;
    operators wanting a `critical` tier must add per-rule overrides in
    deployment overlays.

    Implemented as a thin wrapper over ``_severity_lookup`` -- the JSON
    vocabulary's uppercase keys are stored in ``severity.yml`` alongside
    the SARIF vocabulary's lowercase keys; the two never collide.
    """
    return _severity_lookup(value)


def lookup_severity_sarif(value: str | None) -> str:
    """Map a SARIF result.level value to the canonical four-level model.

    Implemented as a thin wrapper over ``_severity_lookup`` -- the SARIF
    vocabulary's lowercase keys are stored in ``severity.yml`` alongside
    the JSON vocabulary's uppercase keys.
    """
    return _severity_lookup(value)


def _status_lookup(value: str | None) -> str:
    """Apply the YAML status map via the platform applicator.

    Semgrep CLI exposes no finding lifecycle (per the connector page
    section "Enumerations"); ``status.yml`` collapses every recognised
    input to the canonical ``open``. Routing through
    ``src.platform.silver.normalize_status`` keeps the framework
    contract intact even though the lookup degenerates to a single value.
    """
    if value is None or value not in _STATUS_MAP.root:
        return _STATUS_DEFAULT
    return normalize_status(value, _STATUS_MAP)


def _dig(obj: Any, path: str) -> Any:
    """Walk a dotted key path through nested dicts. Return None if any hop misses."""
    cur: Any = obj
    for seg in path.split("."):
        if not isinstance(cur, dict) or seg not in cur:
            return None
        cur = cur[seg]
    return cur


def _first_cwe_from_strings(values: Iterable[str] | None) -> str | None:
    """Return the first CWE-shaped string from an iterable, or None.

    Semgrep encodes CWE in two ways (per connector page section "Resource
    schema excerpt"):

      - JSON: ``extra.metadata.cwe`` is an array of strings like
        ``"CWE-78: Improper Neutralization..."``.
      - SARIF: ``runs[].tool.driver.rules[].properties.tags`` mixes
        many tag types; CWE labels look like ``"CWE-78"`` or
        ``"cwe:78"``.

    Returns the first match, normalised to the ``CWE-<digits>`` form.
    Null when no CWE tag is present (rule-pack drift -- many rules omit).
    """
    if not values:
        return None
    for v in values:
        if not isinstance(v, str):
            continue
        # Accept both "CWE-78" and "cwe:78" shapes; emit canonical form.
        upper = v.strip().upper()
        if upper.startswith("CWE-"):
            # Trim everything after the digits (drop any ": ..." suffix).
            head = upper.split(":", 1)[0]
            return head.strip()
        if upper.startswith("CWE:"):
            num = upper.split(":", 1)[1].strip()
            if num.isdigit():
                return f"CWE-{num}"
    return None


# --------------------------------------------------------------------------- #
# JSON-flavour record projection
# --------------------------------------------------------------------------- #


def record_to_silver_json(
    record: dict,
    *,
    repository_id: str | None,
    trigger_context: Literal["cicd", "periodic"],
) -> dict:
    """Apply the declarative mapping to a single Semgrep `--json` result.

    ``record`` is one element from the top-level ``results[]`` array. The
    artefact-key-derived ``repository_id`` and ``trigger_context`` are
    threaded through because they are NOT present in the document body
    (per mapping.yml section ``derive_from``).
    """
    rule_id = record.get("check_id")
    file_path = record.get("path")
    start_line = _dig(record, "start.line")
    start_col = _dig(record, "start.col")
    end_line = _dig(record, "end.line")
    end_col = _dig(record, "end.col")
    message = _dig(record, "extra.message")
    native_severity = _dig(record, "extra.severity")
    cwe_array = _dig(record, "extra.metadata.cwe")

    cwe_id = _first_cwe_from_strings(cwe_array if isinstance(cwe_array, list) else None)

    finding_id = _build_finding_id(repository_id, file_path, rule_id, start_line)

    return {
        "finding_id": finding_id,
        "tool_source": "semgrep",
        "category": "sast",
        "severity_canonical": _severity_lookup(native_severity),
        # No source vocabulary -- routed through the YAML-driven
        # applicator with the literal "open" as the only recognised key.
        "status_canonical": _status_lookup("open"),
        "cwe_id": cwe_id,
        "rule_id_native": rule_id,
        "rule_id": rule_id,           # carried explicitly so dedup key resolves
        "trigger_context": trigger_context,
        "repository_id": repository_id,
        "file_path": file_path,
        "start_line": start_line,
        "start_column": start_col,
        "end_line": end_line,
        "end_column": end_col,
        "message": message,
        "native_severity": native_severity,
        "url": None,
        # Source timestamp is not present in `--json` output; the artefact
        # filename's commit-SHA / scan-start-ts is the time anchor and is
        # tracked at the lane level via the per-lane HWM.
        "source_timestamp": None,
    }


# --------------------------------------------------------------------------- #
# SARIF-flavour record projection
# --------------------------------------------------------------------------- #


def _sarif_rule_tags(run: dict, rule_index: int | None, rule_id: str | None) -> list[str]:
    """Look up the rule's ``properties.tags`` array via ruleIndex or ruleId."""
    driver = _dig(run, "tool.driver") or {}
    rules = driver.get("rules") or []
    rule: dict | None = None
    if isinstance(rule_index, int) and 0 <= rule_index < len(rules):
        candidate = rules[rule_index]
        if isinstance(candidate, dict):
            rule = candidate
    if rule is None and rule_id is not None:
        for r in rules:
            if isinstance(r, dict) and r.get("id") == rule_id:
                rule = r
                break
    if not rule:
        return []
    tags = _dig(rule, "properties.tags")
    return tags if isinstance(tags, list) else []


def _sarif_first_location(result: dict) -> tuple[str | None, int | None, int | None]:
    """Return ``(file_path, start_line, start_column)`` from the first SARIF location."""
    locations = result.get("locations") or []
    if not locations or not isinstance(locations[0], dict):
        return (None, None, None)
    physical = _dig(locations[0], "physicalLocation") or {}
    artifact_uri = _dig(physical, "artifactLocation.uri")
    region = physical.get("region") or {}
    start_line = region.get("startLine") if isinstance(region, dict) else None
    start_col = region.get("startColumn") if isinstance(region, dict) else None
    return (artifact_uri, start_line, start_col)


def sarif_results_to_silver(
    sarif_doc: dict,
    *,
    repository_id: str | None,
    trigger_context: Literal["cicd", "periodic"],
) -> list[dict]:
    """Project all SARIF results into Silver rows.

    SARIF nests ``results[]`` under ``runs[]``; rule metadata is pulled
    via ``ruleIndex`` (or ``ruleId`` fallback) into
    ``runs[].tool.driver.rules[]``. CWE tags are extracted from
    ``properties.tags`` on the matched rule.
    """
    runs = sarif_doc.get("runs") if isinstance(sarif_doc, dict) else None
    if not isinstance(runs, list):
        return []
    out: list[dict] = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        results = run.get("results") or []
        for result in results:
            if not isinstance(result, dict):
                continue
            rule_id = result.get("ruleId")
            rule_index = result.get("ruleIndex")
            level = result.get("level")
            message = _dig(result, "message.text")
            file_path, start_line, start_col = _sarif_first_location(result)

            tags = _sarif_rule_tags(run, rule_index, rule_id)
            cwe_id = _first_cwe_from_strings(tags)

            finding_id = _build_finding_id(repository_id, file_path, rule_id, start_line)

            out.append(
                {
                    "finding_id": finding_id,
                    "tool_source": "semgrep",
                    "category": "sast",
                    "severity_canonical": _severity_lookup(level),
                    "status_canonical": _status_lookup("open"),
                    "cwe_id": cwe_id,
                    "rule_id_native": rule_id,
                    "rule_id": rule_id,
                    "trigger_context": trigger_context,
                    "repository_id": repository_id,
                    "file_path": file_path,
                    "start_line": start_line,
                    "start_column": start_col,
                    "end_line": None,
                    "end_column": None,
                    "message": message,
                    "native_severity": level,
                    "url": None,
                    "source_timestamp": None,
                }
            )
    return out


# --------------------------------------------------------------------------- #
# Common helpers + dedup
# --------------------------------------------------------------------------- #


def _build_finding_id(
    repository_id: str | None,
    file_path: str | None,
    rule_id: str | None,
    start_line: int | None,
) -> str:
    """Synthesize a stable finding_id from the dedup-key components.

    Rule-pack drift (per connector page section "Quirks" -- "Rule-pack drift")
    means rule IDs may shift across versions; the connector retains the
    rule_id verbatim and lets downstream cross-time analytics join on
    cwe_id + vulnerability_class for stable grouping.
    """
    return f"{repository_id or ''}:{file_path or ''}#{rule_id or ''}@{start_line if start_line is not None else ''}"


def dedup_key_for(row: dict) -> tuple:
    """Return the Bronze->Silver dedup tuple for a Silver-shaped row."""
    return tuple(row.get(k) for k in DEDUP_KEY)


def transform_artefact(
    artefact_format: Literal["json", "sarif"],
    document: dict,
    *,
    repository_id: str | None,
    trigger_context: Literal["cicd", "periodic"],
) -> list[dict]:
    """Transform one artefact (JSON or SARIF) into a list of Silver rows.

    Routes by ``artefact_format`` (which the ingest layer derives from the
    file extension via ``ingest.detect_format``). Both formats produce
    rows under the same Silver schema; the per-row ``native_severity``
    column preserves the source vocabulary for diagnostics.
    """
    if artefact_format == "json":
        results = document.get("results") if isinstance(document, dict) else None
        if not isinstance(results, list):
            return []
        return [
            record_to_silver_json(
                r,
                repository_id=repository_id,
                trigger_context=trigger_context,
            )
            for r in results
            if isinstance(r, dict)
        ]
    if artefact_format == "sarif":
        return sarif_results_to_silver(
            document,
            repository_id=repository_id,
            trigger_context=trigger_context,
        )
    raise ValueError(
        f"unrecognised Semgrep artefact format: {artefact_format!r} "
        f"(expected 'json' or 'sarif')"
    )


def transform(bronze_df):
    """Framework contract wrapper. Returns an empty silver_findings frame.

    The DAB job's Spark-side transform composes ``transform_artefact``
    with ``src.platform.silver.dedup_findings``; the in-process stub
    returns an empty Silver frame so orchestration can chain without a
    runtime error, consistent with the TruffleHog connector pattern.
    """
    from src.platform.schemas import silver_findings

    return bronze_df.sparkSession.createDataFrame([], schema=silver_findings)
