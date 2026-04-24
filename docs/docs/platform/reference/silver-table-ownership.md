# Silver table ownership

Silver tables and connectors do not line up one-to-one. Each table can be fed by multiple connectors; each connector feeds multiple tables. This page makes the mapping explicit so onboarding a new source becomes a checklist of target tables rather than a discovery exercise.

## Onboarding pattern

- A new SCM platform feeds multiple entity tables and optionally contributes platform-integrated findings.
- A new scanner feeds a single finding table and relies on existing SCM connectors for referenced repositories.
- A new enrichment source feeds one reference table.

## Silver table ownership by connector category

| Silver Table | Populated By |
|---|---|
| applications | CMDB |
| repositories | SCM |
| teams | CMDB; SCM |
| commits | SCM |
| pull_requests | SCM |
| pipeline_runs | CI/CD; SCM for platform-integrated pipelines |
| dependencies | SCA scanner; SCM for dependency-graph APIs |
| branch_policies | SCM |
| findings | all scanner categories: SAST, SCA, secret, DAST, container, IaC; also SCM for platform-integrated code/dependency/secret scanning. Records are discriminated by the `category` column. |
| vulnerabilities | NVD enrichment connector |
| epss_scores | EPSS enrichment connector |
| kev_entries | CISA KEV enrichment connector |
| app_repo_mapping | CMDB; SCM |
| finding_cve_mapping | derived in the transformation layer |
| dedup_links | derived in the transformation layer |
