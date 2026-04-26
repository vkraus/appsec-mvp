# Source capability matrix

Capability matrix for the nine sources selected for the reference implementation, covering protocol, pagination, high water mark column, webhook availability, native severity levels, and operational pattern.

The **operational pattern** column distinguishes:

- **periodic-global**: scheduled scans of an enrolled inventory.
- **CI/CD-step**: scans for each commit producing pipeline artifacts.
- **on-demand**: scan per target lifecycle for dynamic scanners.
- **runtime**: continuous event streams read in time windows.
- **platform**: non-scanner sources (CMDB, SCM).

| Source | Protocol | Pagination | HWM | Webhook | Native severity levels | Op. pattern |
|---|---|---|---|---|---|---|
| ServiceNow | REST | offset | sys_updated_on | no | N/A | platform |
| GitHub | REST + GraphQL | cursor | updated_at | yes | 2 (rule + security) | platform |
| GitLab | REST + GraphQL | keyset | updated_at | yes | 6 | platform |
| SonarQube | REST | offset | updateDate | trigger only | 5 (issue) / 3 (hotspot) | periodic-global |
| Semgrep (Docker) | CLI (JSON out) | N/A | commit_sha | no | 3 (CLI) | CI/CD-step |
| Semgrep (Cloud) | REST | cursor | since_date / updated_at | no | 5 | periodic-global |
| Dependency-Track | REST | offset | lastOccurrence | no | 6 | periodic-global |
| TruffleHog | CLI (JSON stdout) | N/A | commit_sha | no | N/A (Verified flag) | CI/CD-step |
| OWASP ZAP | REST | N/A | scan_id | no | 4 (Info–High risk) | on-demand |
| AWS WAF | REST (AWS SDK) | N/A | event_window | no | N/A (action + rule) | runtime |

## Patterns

This matrix drives the standardized Silver Entity and Silver Finding patterns, which must accommodate sources varying across every column. It also drives the connector framework defaults that apply uniformly across ingestion strategies.
