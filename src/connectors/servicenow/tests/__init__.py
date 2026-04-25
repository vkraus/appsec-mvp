"""Test suite for the ServiceNow connector (CMDB).

REQ-ID coverage per ``mkdocs/docs/platform/reference/catalog.md`` traceability
matrix (ServiceNow column):
- REQ-ING-AUTH, REQ-ING-PAG, REQ-ING-RL, REQ-ING-HWM (ingest contract)
- REQ-TRF-MAP, REQ-TRF-TS, REQ-DQ (transform contract)
- REQ-TRF-SEV, REQ-TRF-STS, REQ-DEDUP — N/A (no findings emitted; not bound)
"""
