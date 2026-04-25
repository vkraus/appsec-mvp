# ---------------------------------------------------------------------------
# GitLab connector — runtime module.
#
# Unlike the github connector (which provisions ECR + IAM + a Juice Shop EKS
# namespace for the end-to-end demo), the gitlab connector has no source-side
# resources to manage: the GitLab tenant and target group are user-
# provisioned out-of-band (gitlab.com SaaS or self-hosted).
#
# This module therefore contains no `resource` blocks. It exists for
# structural parity with the other connectors and to surface the canonical
# Bronze schema name + GitLab host as outputs that downstream bundle
# resources (job.yml, ingest pipelines) can resolve from terraform state.
#
# What the user must provision before the bundle deploy:
#
#   1. The GitLab Personal Access Token, loaded into Databricks Secrets via
#      `bash ../scripts/load-secrets.sh` (writes scope=mvp-connectors,
#      key=gitlab_token by default — see variables.tf).
#
#   2. The Bronze schema `${var.catalog}.bronze_gitlab`, declared in
#      `src/connectors/gitlab/resources/schemas.yml` and created by the DAB
#      bundle (`databricks bundle deploy`). This module references the
#      schema's fully-qualified name only; it does not create it.
# ---------------------------------------------------------------------------
