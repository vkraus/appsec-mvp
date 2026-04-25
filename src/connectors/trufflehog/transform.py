"""Bronze-to-silver transform for TruffleHog.

This module realises the declarative mapping at ``mapping.yml`` as pure
Python so unit tests exercise the normalisation rules without a Spark
session. The Databricks entry point in the DAB job wraps this with a
Spark DataFrame applicator.

Dedup key per references/secrets.md:

    (repository_id, commit_sha, secret_type, file_path)

Both per-commit (CI/CD-step) and periodic host-side scans emit records
labelled with ``(repository_id, commit_sha)``; the four-tuple unifies them
without double-counting.

Invariants:

- Severity is a hard-coded literal ``high`` per the mapping. The
  ``config/severity/trufflehog.yml`` file is consulted only when an
  operator deploys a per-detector override.
- Status has no source vocabulary. Literal ``open`` is stamped on every
  row; there is NO status-transition logic. REQ-TRF-STS does not apply
  to secrets sources.
- ``Raw`` and ``RawV2`` MUST NOT enter Silver — only ``Redacted`` is kept.
- ``validity_status`` is derived from TruffleHog's ``Verified`` +
  ``VerificationError`` fields; see ``derive_validity_status``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.connectors.trufflehog.ingest import derive_validity_status

# Fields explicitly dropped at Bronze→Silver — mandatory, not configurable.
DROPPED_FIELDS: tuple[str, ...] = ("Raw", "RawV2")

# Dedup key per references/secrets.md § "Deduplication key".
DEDUP_KEY: tuple[str, ...] = ("repository_id", "commit_sha", "secret_type", "file_path")


def _dig(obj: dict, path: str) -> Any:
    """Walk a dotted key path through nested dicts. Return None if any hop misses."""
    cur: Any = obj
    for seg in path.split("."):
        if not isinstance(cur, dict) or seg not in cur:
            return None
        cur = cur[seg]
    return cur


def _repository_id(repo_url: str | None) -> str | None:
    """Derive a stable repository_id from the Git repository URL.

    TruffleHog's ``SourceMetadata.Data.Git.repository`` is the upstream URL
    (e.g. ``https://github.com/acme/payments-api``). The connector collapses
    it to ``<owner>/<repo>`` to align with the repository_id shape produced
    by the GitHub SCM connector (``acme/payments-api``) so dedup across
    sources uses the same key.
    """
    if not repo_url:
        return None
    # Strip scheme, host, and any trailing ``.git`` suffix.
    stripped = repo_url
    for scheme in ("https://", "http://", "git@", "ssh://git@"):
        if stripped.startswith(scheme):
            stripped = stripped[len(scheme):]
            break
    # Strip host and leading colon (for git@host:owner/repo shape).
    if ":" in stripped and "/" in stripped and stripped.index(":") < stripped.index("/"):
        stripped = stripped.split(":", 1)[1]
    elif "/" in stripped:
        stripped = stripped.split("/", 1)[1]
    if stripped.endswith(".git"):
        stripped = stripped[: -len(".git")]
    return stripped or None


def record_to_silver(record: dict) -> dict:
    """Apply the declarative mapping to a single TruffleHog JSON record.

    Returns a dict with canonical Silver-layer field names. ``Raw`` and
    ``RawV2`` are excluded by construction — they are never read from the
    input. Callers are responsible for downstream dedup on ``DEDUP_KEY``.
    """
    git_leaf = _dig(record, "SourceMetadata.Data.Git") or {}
    repo_url = git_leaf.get("repository")
    commit_sha = git_leaf.get("commit")
    file_path = git_leaf.get("file")
    start_line = git_leaf.get("line")
    timestamp = git_leaf.get("timestamp")

    detector_name = record.get("DetectorName")
    verified = record.get("Verified")
    verification_error = record.get("VerificationError") or None
    redacted = record.get("Redacted")

    repository_id = _repository_id(repo_url)

    finding_id_parts = [
        repo_url or "",
        commit_sha or "",
        file_path or "",
        detector_name or "",
    ]
    finding_id = "@".join(finding_id_parts[:2]) + ":" + finding_id_parts[2] + "#" + finding_id_parts[3]

    return {
        "finding_id": finding_id,
        "tool_source": "trufflehog",
        "category": "secrets",
        "severity_canonical": "high",  # hard-coded per references/secrets.md
        "status_canonical": "open",    # no source vocabulary; literal constant
        "cwe_id": None,
        "rule_id_native": detector_name,
        "secret_type": detector_name,  # DetectorName substitutes for rule_id
        "repository_id": repository_id,
        "commit_sha": commit_sha,
        "file_path": file_path,
        "start_line": start_line,
        "url": None,
        "redacted": redacted,
        "validity_status": derive_validity_status(verified, verification_error),
        "source_timestamp": timestamp,
    }


def dedup_key_for(row: dict) -> tuple:
    """Return the Bronze→Silver dedup tuple for a Silver-shaped row."""
    return tuple(row.get(k) for k in DEDUP_KEY)


def transform_records(records: Iterable[dict]) -> list[dict]:
    """Apply ``record_to_silver`` across a batch. Preserves input order.

    Dedup on ``DEDUP_KEY`` is performed downstream in the Spark transform
    (``src.platform.silver.dedup_findings`` handles the generic case); this
    function is the per-record projection that unit tests exercise.
    """
    return [record_to_silver(r) for r in records]


def transform(bronze_df):
    """Framework contract wrapper. Returns an empty silver_findings frame.

    The DAB job's Spark-side transform composes ``record_to_silver`` with
    ``src.platform.silver.dedup_findings``; the in-process stub returns an
    empty Silver frame so orchestration can chain without a runtime error,
    consistent with the Semgrep connector pattern.
    """
    from src.platform.schemas import silver_findings

    return bronze_df.sparkSession.createDataFrame([], schema=silver_findings)
