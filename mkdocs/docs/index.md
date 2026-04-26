---
hide:
  - toc
---

<div class="hero" markdown>

<span class="eyebrow">Application Security · Databricks Reference MVP</span>

# Unify AppSec findings across CMDB, SCM, SAST, SCA, Secrets, DAST, and WAF.

<p class="subtitle">An MVP implementation of a data integration framework for application security, built on Databricks.</p>

<div class="actions" markdown>
[Start setup →](platform/index.md){ .md-button .md-button--primary }
[View on GitHub](https://github.com/vkraus/appsec-mvp){ .md-button }
</div>

</div>

<div class="landing-overview" markdown>

The platform ingests from AppSec sources via a connector for each source, normalizes findings to recommended schemas, and exposes analytics over them. The reference implementation runs on Databricks and is packaged as an Asset Bundle.

```mermaid
flowchart LR
  subgraph Sources["Sources"]
    direction TB
    GH[GitHub]
    GL[GitLab]
    SN[ServiceNow CMDB]
    SQ[SonarQube]
    SG[Semgrep]
    DT[Dependency-Track]
    TH[TruffleHog]
    ZAP[OWASP ZAP]
    WAF[AWS WAF]
  end

  subgraph Bronze["Bronze (raw)"]
    direction TB
    BG[bronze_github]
    BGL[bronze_gitlab]
    BSN[bronze_servicenow]
    BSQ[bronze_sonarqube]
    BSG[bronze_semgrep]
    BDT[bronze_dependency_track]
    BTH[bronze_trufflehog]
    BZAP[bronze_owasp_zap]
    BWAF[bronze_aws_waf]
  end

  subgraph Silver["Silver (canonical entities)"]
    SR["silver.repositories"]
    SA["silver.applications"]
    SAR["silver.app_repo_mapping"]
    SF["silver.findings"]
    SW["silver.waf_events"]
    SS["silver.suppression_rules"]
  end

  subgraph Gold["Gold (analytics — 5 OLAP Delta tables refreshed daily + 1 view)"]
    direction TB
    GR1["gold.app_risk_posture_daily"]
    GR2["gold.mttr_by_source_severity_weekly"]
    GR3["gold.coverage_matrix"]
    GR4["gold.dedup_link_overlap"]
    GR5["gold.cwe_owasp_heatmap"]
    GVIEW["gold.app_repo_findings_open
(view)"]
  end

  subgraph OLTP["OLTP serving (Online Tables, ~5 min lag)"]
    OAR["gold_online.app_risk_posture"]
    OARF["silver_online.app_repo_findings"]
  end

  subgraph Consumers["Consumers"]
    APP["Databricks App
(security-score endpoint)"]
    DASH["Dashboards & SQL"]
  end

  GH --> BG
  GL --> BGL
  SN --> BSN
  SQ --> BSQ
  SG --> BSG
  DT --> BDT
  TH --> BTH
  ZAP --> BZAP
  WAF --> BWAF

  BG --> SR
  BGL --> SR
  BSN --> SA
  BSQ --> SF
  BSG --> SF
  BDT --> SF
  BTH --> SF
  BZAP --> SF
  BWAF --> SW

  SR --> SAR
  SA --> SAR

  SR --> SF
  SAR --> SF

  SF --> GR1
  SF --> GR2
  SF --> GR3
  SF --> GR4
  SF --> GR5
  SAR --> GR1
  SAR --> GR5
  SR --> GR3
  SS --> GR1
  SS --> GR2
  SS --> GR4
  SS --> GR5

  SF --> GVIEW
  SAR --> GVIEW

  GR1 --> OAR
  GVIEW --> OARF

  OAR --> APP
  OARF --> APP
  GR1 --> DASH
  GR2 --> DASH
  GR3 --> DASH
  GR4 --> DASH
  GR5 --> DASH
```

</div>

## Install order

<div class="grid cards" markdown>

-   :material-server-network:{ .lg .middle } **1. [Setup platform](platform/index.md)**

    ---

    Workspace bootstrap: catalog, schemas, jobs, secrets.

-   :material-power-plug:{ .lg .middle } **2. [Install connectors](connectors/index.md)**

    ---

    Wire each AppSec source.

-   :material-chart-line:{ .lg .middle } **3. [Build analytics](analytics/index.md)**

    ---

    Gold datasets, evidence scenarios, dashboards.

</div>

### Connector categories

<div class="grid cards" markdown>

-   :material-source-branch:{ .lg .middle } **1. [SCM](connectors/scm/index.md)**

    ---

    GitHub, GitLab. Must be installed first; populates `silver.repositories`.

-   :material-database:{ .lg .middle } **2. [CMDB](connectors/cmdb/index.md)**

    ---

    ServiceNow.

-   :material-magnify-scan:{ .lg .middle } **3. [SAST](connectors/sast/index.md)**

    ---

    SonarQube, Semgrep.

-   :material-package-variant:{ .lg .middle } **4. [SCA](connectors/sca/index.md)**

    ---

    Dependency-Track.

-   :material-key-variant:{ .lg .middle } **5. [Secrets](connectors/secrets/index.md)**

    ---

    TruffleHog.

-   :material-bug-check:{ .lg .middle } **6. [DAST](connectors/dast/index.md)**

    ---

    OWASP ZAP.

-   :material-shield-check:{ .lg .middle } **7. [WAF](connectors/waf/index.md)**

    ---

    AWS WAF.

</div>
