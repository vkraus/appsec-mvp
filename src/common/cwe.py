"""CWE extraction. Each SAST tool exposes CWE differently; this module
normalizes them to the form CWE-<number>."""

import re

_CWE_NUMBER_RE = re.compile(r"CWE[-:\s]?(\d+)", re.IGNORECASE)


def _canonicalize(raw: str | int) -> str | None:
    if isinstance(raw, int):
        return f"CWE-{raw}"
    m = _CWE_NUMBER_RE.search(str(raw))
    if m:
        return f"CWE-{m.group(1)}"
    # Bare digit string
    if str(raw).strip().isdigit():
        return f"CWE-{str(raw).strip()}"
    return None


def extract_cwe_from_sonarqube(issue: dict) -> str | None:
    # Modern field
    cwes = issue.get("cwe")
    if cwes:
        first = cwes[0] if isinstance(cwes, list) else cwes
        return _canonicalize(first)
    # Older field: securityStandards = ["cwe:89", "owaspTop10:a3"]
    standards = issue.get("securityStandards") or []
    for s in standards:
        if str(s).lower().startswith("cwe:"):
            return _canonicalize(str(s).split(":", 1)[1])
    return None


def extract_cwe_from_semgrep(finding: dict) -> str | None:
    metadata = finding.get("extra", {}).get("metadata", {})
    cwe = metadata.get("cwe")
    if cwe is None:
        return None
    if isinstance(cwe, list):
        cwe = cwe[0] if cwe else None
    if cwe is None:
        return None
    return _canonicalize(cwe)
