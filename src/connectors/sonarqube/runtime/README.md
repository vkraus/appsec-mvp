# SonarQube connector — source-system runtime (optional)

This Terraform module deploys the **SonarQube server** that the SonarQube connector ingests from. It runs SonarQube on the operator-supplied EKS cluster and either creates a dedicated RDS Postgres database for SonarQube's backing store or uses an operator-supplied one.

**It is optional.** The SonarQube connector itself only needs a SonarQube URL + analysis token — operators with their own SonarQube instance skip this module entirely.

## When to apply

Apply this module if you want appsec-mvp to provision SonarQube end-to-end (Helm release on EKS + Postgres). Skip it if you have your own SonarQube tenant; in that case feed your `SONARQUBE_URL` and project analysis token directly into the connector's secrets.

## What it creates

- A SonarQube Helm release in the `sonarqube` Kubernetes namespace on your EKS cluster, exposed via a LoadBalancer Service on port 9000.
- A `sonarqube-db` Kubernetes Secret holding the JDBC connection string Sonar reads at boot.
- (Optional, when `rds_endpoint` is empty) A dedicated RDS Postgres instance (`db.t3.small`, 20 GiB, Postgres 15), a DB subnet group, a security group allowing port 5432 from the supplied VPC CIDR, and a random 32-char password.
- A 40-char random opaque value emitted as `sonarqube_project_token` for use as the project analysis token (the Helm chart does not support declarative token creation, so the operator registers it with SonarQube post-install).

## Operator-supplied inputs

### Required

| Variable | Description |
|---|---|
| `aws_region` | AWS region for EKS + (optional) RDS. Must match the region of `eks_cluster_name`. |
| `aws_access_key_id`, `aws_secret_access_key` | AWS credentials (sensitive). |
| `eks_cluster_name` | EKS cluster where SonarQube is installed. Must be in `var.aws_region`. |
| `sonarqube_admin_password` | Initial Sonar admin / monitoring passcode (sensitive). |

### Optional

| Variable | Description | Default |
|---|---|---|
| `project_prefix` | Tag/name prefix for AWS resources (RDS identifier, security group, subnet group). | `appsec-mvp` |
| `sonarqube_namespace` | Kubernetes namespace for the Helm release. | `sonarqube` |
| `sonarqube_chart_version` | SonarQube Helm chart version. | `10.6.1+2742` |
| `rds_endpoint` | Pre-existing Postgres endpoint (host:port). Empty string → this module creates RDS. | `""` |
| `rds_db_name` | Postgres database name. | `sonar` |
| `rds_username` | Postgres username (master username when this module creates RDS). | `sonar` |
| `rds_password` | Required when `rds_endpoint` is non-empty (sensitive). When empty, a random password is generated for the RDS this module creates. | `""` |
| `rds_instance_class`, `rds_allocated_storage`, `rds_engine_version`, `rds_parameter_group_family` | Tunables for the RDS instance this module creates. Unused when `rds_endpoint` is supplied. | `db.t3.small`, `20`, `15`, `postgres15` |
| `vpc_id`, `vpc_subnet_ids`, `vpc_cidr_block` | **Required when `rds_endpoint` is empty** (this module creates its own RDS). Unused when `rds_endpoint` is supplied. | `""`, `[]`, `""` |

## Apply

```bash
cd src/connectors/sonarqube/runtime
terraform init
terraform apply -var-file=terraform.tfvars
```

Operators write their own `terraform.tfvars`. The legacy `infra/terraform/terraform.tfvars.example` can serve as a starting reference.

## Outputs

`sonarqube_url` (Kubernetes service URL — feed this into the SonarQube connector's `SONARQUBE_URL` secret), `sonarqube_namespace`, `sonarqube_project_token` (sensitive — register with SonarQube post-install), `rds_endpoint`, `rds_db_name`, `rds_username`, `rds_password` (sensitive).

## Teardown

```bash
cd src/connectors/sonarqube/runtime
terraform destroy
```

Caveats:
- The Helm release destroy can hang on PV cleanup if the Sonar PVC has data; if it stalls, `kubectl delete pvc -n sonarqube --all` first, then re-run.
- RDS deletion uses `skip_final_snapshot = true` (demo defaults — change in `main.tf` if you want a snapshot before drop).
- The RDS security group depends on no resources outside this module, so destroy is order-safe.

## Independence

This module references only operator-supplied inputs and the AWS / Kubernetes / Helm provider APIs. It does not depend on any other connector's runtime — per the redesign's no-inter-connector-dependency rule. Cross-runtime references that previously came from `aws-foundation` outputs (`eks_cluster_name`, `vpc_id`, `vpc_subnet_ids`, `vpc_cidr_block`) become operator-supplied variables.
