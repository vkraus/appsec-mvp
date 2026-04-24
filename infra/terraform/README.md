# Terraform — MVP operator procedure

This tree is the infrastructure-as-code half of the operator procedure described at
[https://vkraus.github.io/appsec-docs/platform/terraform-apply/](https://vkraus.github.io/appsec-docs/platform/terraform-apply/)
(source: [`appsec-docs/docs/platform/terraform-apply.md`](https://github.com/vkraus/appsec-docs/blob/main/docs/platform/terraform-apply.md)).

See the docs page for the walkthrough. This README is a compact reference for engineers
who are already familiar with Terraform.

## Layout

- `main.tf` wires the five modules.
- `modules/aws-foundation` — VPC, EKS, RDS, S3, ECR, IAM (including the GitHub OIDC role).
- `modules/scanners-eks` — SonarQube, Semgrep CronJob, ZAP, Juice Shop namespace.
- `modules/databricks-workspace` — UC catalogs/schemas, secret scopes, Lakeflow Connect pipeline, DAB jobs.
- `modules/github-seed` — three seed repositories + Juice Shop CI/CD workflow + Actions secrets.
- `modules/servicenow-seed` — CMDB business-app records.

## Quick start

```bash
cp terraform.tfvars.example terraform.tfvars   # fill in credentials
terraform init
terraform apply
```
