# ---------------------------------------------------------------------------
# SonarQube connector — runtime module.
#
# The sonarqube connector has no source-side resources to manage: the
# SonarQube server (SonarCloud SaaS or self-hosted SonarQube CE) is operator-
# provisioned out-of-band.
#
# This module therefore contains no `resource` blocks. It exists for
# structural parity with the other connectors and to surface the canonical
# Bronze schema name + SonarQube host as outputs that downstream bundle
# resources (job.yml, ingest pipelines) can resolve from terraform state.
#
# What the operator must provision before the bundle deploy:
#
#   1. The SonarQube user token, loaded into Databricks Secrets via
#      `bash ../scripts/load-secrets.sh` (writes scope=mvp-connectors,
#      key=sonarqube_token by default — see variables.tf).
#
#   2. The Bronze schema `${var.catalog}.bronze_sonarqube`, declared in
#      `src/connectors/sonarqube/resources/schemas.yml` and created by the DAB
#      bundle (`databricks bundle deploy`). This module references the
#      schema's fully-qualified name only; it does not create it.
# ---------------------------------------------------------------------------
