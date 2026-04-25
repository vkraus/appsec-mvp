# SonarQube connector — runtime module

Terraform module that wires the SonarQube connector into a Databricks workspace.

The SonarQube server itself (SonarCloud SaaS or self-hosted SonarQube CE) is operator-provisioned out-of-band, so this module contains no `resource` blocks. It exists for structural parity — it pins providers, declares operator inputs, and exports the canonical Bronze schema name and SonarQube host so downstream bundle resources can resolve them from terraform state.

## Prerequisites

- A SonarCloud account (<https://sonarcloud.io>) or a self-hosted SonarQube Community Edition instance reachable from the Databricks workspace.
- A SonarCloud organization, or — for self-hosted SonarQube — the literal value `default`. SonarCloud's organization key is visible at <https://sonarcloud.io/account/organizations>.
- A SonarQube user token with `Browse projects` and `Execute analysis` permissions on every project to be ingested. An admin token works too. Generate at **My Account → Security → Generate Tokens** in the SonarQube UI; choose token type `User Token` (broader scope than `Project Analysis Token`, required for cross-project enumeration via `/api/projects/search`). Recommended expiry: 90 days, with rotation procedure documented in the parent operations runbook.
- The Unity Catalog catalog (e.g. `appsec_dev`) and the bundle-managed `bronze_sonarqube` schema declared in `src/connectors/sonarqube/resources/schemas.yml`. Apply `databricks bundle deploy` once before the first connector run.

## Setup

1. Export the token into your shell:

   ```bash
   export SONARQUBE_TOKEN="<your-user-token>"
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
     -var "sonarqube_organization=<your-org-key>"
   ```

   Override `sonarqube_host` for self-hosted SonarQube (`-var "sonarqube_host=sonarqube.example.com"`); override `sonarqube_token_secret_scope` / `sonarqube_token_secret_key` only if your org uses a non-default Databricks secret layout.

## Outputs

- `bronze_schema_full_name` — fully-qualified Bronze schema name (`catalog.bronze_sonarqube`); downstream bundle jobs reference this as the ingestion target.
- `sonarqube_host` — echoes the SonarQube tenant host for downstream bundle resolution.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `databricks_secret not found` at pipeline runtime | Operator did not run `load-secrets.sh`; re-run after exporting `$SONARQUBE_TOKEN`. |
| `401 Unauthorized` from SonarQube API at runtime | Token expired, revoked, or has insufficient permissions; rotate the user token (ensure `Browse projects` + `Execute analysis` on all target projects) and re-run `load-secrets.sh`. |
| `403 Forbidden` on `/api/projects/search` | Token has project-analysis scope only; regenerate as a user token instead. |
| Empty `bronze_sonarqube` schema after pipeline run | `sonarqube_organization` may be wrong; verify via `curl -H "Authorization: Bearer $SONARQUBE_TOKEN" https://$SONARQUBE_HOST/api/organizations/search?member=true`. |
| `Schema bronze_sonarqube does not exist` | Bundle has not been deployed yet; run `databricks bundle deploy --target dev` before the first ingest job. |

## Validation evidence

(populated in production-shape-c after live deploy)
