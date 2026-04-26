"""Pre-merge gate policy logic for the AppSec analytics App.

Reads ``policy.yml``, applies the configured severity threshold to a list of
candidate findings, and returns ``(allow, blocking_findings, summary)``.

The default policy blocks the PR if any candidate finding has
``severity_canonical`` at or above the threshold (default: ``high``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# Canonical severity ladder, lowest to highest. Matches
# ``mkdocs/docs/platform/reference/canonical-mapping.md``.
SEVERITY_RANK: dict[str, int] = {
    "info": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}

DEFAULT_THRESHOLD = "high"


def load_policy(path: Path) -> dict[str, Any]:
    """Load the policy YAML.

    Returns a dict with at least ``block_severity_threshold`` set; missing
    keys fall back to sensible defaults so the App still serves traffic if
    the policy file is partially populated.
    """
    if not path.exists():
        return {"block_severity_threshold": DEFAULT_THRESHOLD}

    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    threshold = raw.get("block_severity_threshold", DEFAULT_THRESHOLD)
    if not isinstance(threshold, str) or threshold.lower() not in SEVERITY_RANK:
        threshold = DEFAULT_THRESHOLD

    return {"block_severity_threshold": threshold.lower()}


def evaluate(
    findings: list[dict[str, Any]],
    policy: dict[str, Any],
) -> tuple[bool, list[dict[str, Any]], str]:
    """Apply ``policy`` to ``findings``.

    A finding blocks the PR iff its ``severity_canonical`` rank is greater
    than or equal to the policy threshold rank. Findings without a
    recognised severity are ignored (treated as ``info``).

    Returns ``(allow, blocking_findings, summary)``:
      - ``allow``: True iff no finding meets or exceeds the threshold.
      - ``blocking_findings``: the subset of ``findings`` that block.
      - ``summary``: human-readable one-liner describing the verdict.
    """
    threshold = policy.get("block_severity_threshold", DEFAULT_THRESHOLD)
    threshold_rank = SEVERITY_RANK.get(threshold, SEVERITY_RANK[DEFAULT_THRESHOLD])

    blocking: list[dict[str, Any]] = []
    for f in findings:
        sev = (f.get("severity_canonical") or "").lower()
        rank = SEVERITY_RANK.get(sev, 0)
        if rank >= threshold_rank:
            blocking.append(f)

    if not findings:
        return True, [], "No candidate findings supplied; allow."

    if not blocking:
        return (
            True,
            [],
            f"No candidate finding meets or exceeds threshold '{threshold}'; allow.",
        )

    return (
        False,
        blocking,
        f"{len(blocking)} of {len(findings)} candidate findings meet or exceed "
        f"threshold '{threshold}'; block.",
    )
