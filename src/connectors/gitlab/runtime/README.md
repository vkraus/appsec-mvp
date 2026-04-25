# GitLab connector, runtime module

Terraform module that wires the GitLab connector into a Databricks workspace.

Unlike the runtime for the github connector (which provisions ECR, IAM, and an EKS namespace for the end to end demo), the gitlab connector has no resources to manage on the source side. The GitLab tenant and target group are provisioned by the operator out of band. This module exists for structural parity. It pins providers, declares operator inputs, and exports the published Bronze schema name and GitLab host so downstream bundle resources can resolve them from terraform state.

## Prerequisites

- A GitLab account (gitlab.com tenant or self hosted GitLab CE >= 16.x).
- A group under your account that the connector will ingest from. The operator obtains the numeric group ID from **Settings → General → "Group ID"** on the group page in the GitLab UI.
- A Personal Access Token with scopes: `read_api`, `read_repository`, `read_user`. Generate at <https://gitlab.com/-/user_settings/personal_access_tokens>. Recommended expiry is 90 days, with the rotation procedure documented in the parent operations runbook.
- The Unity Catalog catalog (e.g. `appsec_dev`) and the `bronze_gitlab` schema managed by the bundle, declared in `src/connectors/gitlab/resources/schemas.yml`. Apply `databricks bundle deploy` once before the first connector run.

## Setup

1. Export the token into your shell:

   ```bash
   export GITLAB_TOKEN="<your-PAT>"
   ```

2. Load the token into Databricks Secrets:

   ```bash
   bash ../scripts/load-secrets.sh
   ```

3. Apply the terraform module:

   ```bash
   terraform init
   terraform apply \
     -var "catalog=appsec_dev" \
     -var "gitlab_group_id=<your-group-id>"
   ```

   Override `gitlab_host` for self hosted GitLab (`-var "gitlab_host=gitlab.example.com"`). Override `gitlab_token_secret_scope` or `gitlab_token_secret_key` only if your org uses a Databricks secret layout that differs from the default.

## Outputs

- `bronze_schema_full_name`. The fully qualified Bronze schema name (`catalog.bronze_gitlab`). Downstream bundle jobs reference this as the ingestion target.
- `gitlab_host`. Echoes the GitLab tenant host for downstream bundle resolution.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `databricks_secret not found` at pipeline runtime | Operator did not run `load-secrets.sh`. Re-run after exporting `$GITLAB_TOKEN`. |
| `401 Unauthorized` from GitLab API at runtime | Token expired or has wrong scopes. Rotate the PAT and re-run `load-secrets.sh`. |
| Empty `bronze_gitlab` schema after pipeline run | `gitlab_group_id` may be wrong. Verify via `curl -H "PRIVATE-TOKEN: $GITLAB_TOKEN" https://gitlab.com/api/v4/groups/<id>`. |
| `Schema bronze_gitlab does not exist` | Bundle has not been deployed yet. Run `databricks bundle deploy --target dev` before the first ingest job. |

## Validation evidence

(populated in production scope c after live deploy)
