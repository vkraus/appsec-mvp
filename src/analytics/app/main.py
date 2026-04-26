"""FastAPI service for the AppSec analytics OLTP layer.

Two routes:

- ``GET /v1/score?app_id=<id>`` — security score lookup against
  ``gold_online.app_risk_posture``.
- ``POST /v1/precommit?repo=<repo>&pr=<pr_id>`` — pre-merge gate.
  Body: ``{ "candidate_finding_ids": [...] }``. The CI/CD caller passes the
  finding ids it would introduce; the App fetches their severities from
  ``silver_online.app_repo_findings`` and applies policy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query

from . import queries
from .policy import evaluate, load_policy

POLICY_PATH = Path(__file__).parent / "policy.yml"

app = FastAPI(
    title="AppSec analytics App",
    description=(
        "OLTP serving for AppSec analytics — security score lookup + "
        "CI/CD pre-merge gate."
    ),
)


@app.get("/v1/score")
def get_score(app_id: str = Query(..., description="application_id to look up")) -> dict[str, Any]:
    """Return the latest open-finding score breakdown for an application."""
    with queries.connect() as conn:
        result = queries.fetch_score(app_id, conn)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No risk-posture rows found for application_id={app_id!r}",
        )
    return result


@app.post("/v1/precommit")
def post_precommit(
    repo: str = Query(..., description="repository identifier (passed through)"),
    pr: str = Query(..., alias="pr_id", description="pull-request identifier"),
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Evaluate the pre-merge gate for a list of candidate findings.

    The CI/CD caller supplies the ids of findings it would introduce; the
    App fetches their severities from ``silver_online.app_repo_findings``
    and applies the configured policy.
    """
    candidate_ids = body.get("candidate_finding_ids", []) or []
    if not isinstance(candidate_ids, list):
        raise HTTPException(
            status_code=400,
            detail="candidate_finding_ids must be a list of strings",
        )

    policy = load_policy(POLICY_PATH)

    if not candidate_ids:
        return {
            "allow": True,
            "blocking_findings": [],
            "policy_summary": "No candidate findings supplied; allow.",
            "repo": repo,
            "pr_id": pr,
        }

    with queries.connect() as conn:
        findings = queries.fetch_findings(candidate_ids, conn)

    allow, blocking, summary = evaluate(findings, policy)
    return {
        "allow": allow,
        "blocking_findings": blocking,
        "policy_summary": summary,
        "repo": repo,
        "pr_id": pr,
    }
