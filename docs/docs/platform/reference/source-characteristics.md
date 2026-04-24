# Source integration characteristics

Integration characteristics across all AppSec source categories covered by the platform analysis.

| Source Category | API | Format | Frequency | Standardization |
|---|---|---|---|---|
| Application Inventory | REST | JSON | Low | Low |
| Cloud Assets | REST | JSON | Continuous | Medium |
| SCM Platforms | REST/GraphQL | JSON | Medium | High |
| Issue Trackers | REST | JSON | Medium | Medium |
| CI/CD Platforms | REST/XML | JSON/XML | Medium | Medium |
| SAST | REST/CLI | JSON/SARIF | On-demand | Medium |
| SCA | REST/GraphQL | JSON | Continuous | High |
| Secret Scanning | CLI/REST | JSON | On-demand | Low |
| Container Scanning | CLI | JSON/SARIF | On-demand | Medium |
| IaC Scanning | CLI | JSON/SARIF | On-demand | Medium |
| DAST | REST/CLI | JSON/XML | On-demand | Medium |
| Penetration Testing | None | PDF | Periodic | None |
| WAF/DDoS | REST | JSON | Continuous | Low |
| RASP | Vendor-specific | JSON | Continuous | Low |
| API Security | REST | JSON | Continuous | Low |
| VMDR/CSPM | REST/GraphQL | JSON/XML | Continuous | Medium |

## Patterns

REST APIs with JSON responses are dominant, but XML, GraphQL, CLI output parsing, and manual uploads are all necessary. Standardization varies: SCA benefits from the CVE/NVD ecosystem, SAST is partially standardized through SARIF, and secret scanning has no standard format. Update frequencies range from continuous dependency monitoring to periodic penetration tests.
