# Terraform Apply

A single `terraform apply` provisions the AWS + EKS + Databricks + GitHub + ServiceNow infrastructure. This page walks the graph so you can reason about partial failures.

## Repo layout

```
infra/terraform/
  main.tf                       # module wiring
  modules/
    aws-foundation/             # VPC, EKS, RDS, S3, ECR, IAM (GitHub OIDC + Databricks external location)
    scanners-eks/               # SonarQube, Semgrep CronJob, ZAP, Juice Shop namespace
    databricks-workspace/       # UC catalogs, secret scopes, Lakeflow Connect pipeline, connector jobs
    github-seed/                # SAST seed repos, Juice Shop fork, CI/CD workflow, Actions secrets
    servicenow-seed/            # CMDB business-apps + application CIs + links
```

## Apply order (automatic via dependency graph)

1. **`aws-foundation`** — ~15 minutes. Creates the VPC, EKS cluster, managed node group, RDS Postgres (SonarQube DB), S3 artifact bucket, ECR repository, and IAM resources (GitHub OIDC provider, Actions role, Databricks external-location role, Semgrep IRSA role).
2. **`scanners-eks`** — ~10 minutes. Helm-installs SonarQube against the RDS DB; creates the Semgrep CronJob; deploys ZAP as a daemon; reserves the Juice Shop namespace and LoadBalancer Service.
3. **`databricks-workspace`** — ~5 minutes. Creates the `appsec_<env>` Unity Catalog (named from the `catalog_name` variable, e.g. `appsec_dev`), external location over the S3 bucket, secret scopes populated from your tfvars, the Lakeflow Connect pipeline pointing at your ServiceNow tenant, and the scheduled connector jobs.
4. **`github-seed`** — ~3 minutes. Creates the two SAST seed repos with their deliberately-vulnerable code, forks Juice Shop, commits the CI/CD workflow, sets the Actions variables and secrets.
5. **`servicenow-seed`** — ~1 minute. Writes the business-app records, application CIs, and linking relationships via the ServiceNow REST API.

## Run it

```bash
cd infra/terraform
terraform init
terraform apply
```

Review the plan summary carefully — first apply creates ~80 resources.

## Bootstrapping SonarQube's analysis token

After the first apply completes, the SonarQube server is running but the project-analysis token declared in `scanners-eks` exists only as a random string in Terraform state. Register it on the SonarQube side with a one-time bootstrap:

```bash
SONAR_URL=$(terraform output -raw sonarqube_url)
SONAR_TOKEN=$(terraform output -raw sonarqube_project_token)

# Log in (first-time admin password is the tfvars value).
curl -X POST "$SONAR_URL/api/user_tokens/generate" \
  -u "admin:$(terraform output -raw sonarqube_admin_password)" \
  -d "name=juiceshop&login=admin&type=PROJECT_ANALYSIS_TOKEN&projectKey=juiceshop"
```

The `juiceshop` project is created on the first Sonar scan from the Juice Shop CI/CD workflow.

## Outputs you will need

```bash
terraform output
```

Captures:

- `databricks_workspace_url`, `sonarqube_url`, `zap_url`, `github_org`, `servicenow_instance_url`
- `semgrep_artifact_bucket`, `ecr_registry_uri`, `juiceshop_namespace`, `juiceshop_ingress_host`

The per-connector runbooks reference these output names verbatim.

## Destroy

```bash
terraform destroy
```

Takes ~15 minutes — EKS teardown is the long tail. All AWS resources have `force_destroy` / `skip_final_snapshot` so no leftover state is retained.

## Next

Walk the [connector](../connectors/) runbooks in order: ServiceNow → GitHub → SonarQube → Semgrep → OWASP ZAP.
