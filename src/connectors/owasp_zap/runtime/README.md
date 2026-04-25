# OWASP ZAP connector — source-system runtime (optional)

This Terraform module deploys an **OWASP ZAP daemon** on the operator's EKS cluster, exposed via a LoadBalancer Service. The OWASP ZAP connector then drives the daemon (typically from a CI workflow that triggers scans against a target URL via the ZAP API) and ingests the resulting findings.

**It is optional.** The OWASP ZAP connector itself only needs a ZAP daemon URL + API key; operators with their own ZAP deployment skip this module entirely and feed their existing endpoint directly into the connector's secrets.

## When to apply

Apply this module if you want appsec-mvp to provision a ZAP daemon on your EKS cluster. Skip it if you have your own ZAP instance — in that case wire the existing daemon's URL and API key into the OWASP ZAP connector secrets directly.

## What it creates

- A `zap` Kubernetes namespace on your EKS cluster.
- A random 40-character ZAP API key, stored in a kubernetes secret as the `ZAP_API_KEY` env var.
- A ZAP Deployment (`replicas = 1`) running `owasp/zap2docker-stable:2.14.0` in daemon mode on container port 8080. The container command is `zap.sh -daemon -host 0.0.0.0 -port 8080 -config api.key=$(ZAP_API_KEY) -config api.addrs.addr.name=.* -config api.addrs.addr.regex=true` (faithful to the source module).
- A LoadBalancer Service exposing the daemon publicly on `var.service_port` (default `8080`). The `zap_url` output gives the resulting public URL.

The runtime is pure Kubernetes — no IRSA, no IAM role, no S3 grants. (The LoadBalancer Service does cause AWS to provision an ELB on the cluster's behalf, but that is managed transparently by the EKS cloud-controller-manager, not by this module.)

> **Security note:** the Deployment runs ZAP with `api.addrs.addr.name=.*` + `api.addrs.addr.regex=true`, which whitelists *all caller IPs* against the ZAP API. Combined with the public LoadBalancer Service, this means the daemon's API is internet-facing and the only access control is the 40-character random API key. This is faithful to the upstream demo configuration. **Production deployments should front the daemon with a Kubernetes NetworkPolicy, a private (`internal`-mode) LoadBalancer, or a VPN gateway** — and consider tightening `api.addrs.addr.*` to a specific caller IP/range.

## Operator-supplied inputs

### Required

| Variable | Description |
|---|---|
| `aws_region` | AWS region of the EKS cluster. Must match the region of `eks_cluster_name`. |
| `aws_access_key_id`, `aws_secret_access_key` | AWS credentials (sensitive). |
| `eks_cluster_name` | EKS cluster where the ZAP daemon is installed. Must be in `var.aws_region`. |

### Optional

| Variable | Description | Default |
|---|---|---|
| `project_prefix` | Tag/name prefix for AWS resources. | `appsec-mvp` |
| `namespace_name` | Kubernetes namespace name. | `zap` |
| `zap_image` | Container image used by the Deployment. Captured as a variable for reproducibility — the source module hard-coded the `2.14.0` tag. | `owasp/zap2docker-stable:2.14.0` |
| `service_port` | Public port on the LoadBalancer Service. The daemon's container port stays at 8080; only the externally-exposed Service port changes. | `8080` |

## Apply

```bash
cd src/connectors/owasp_zap/runtime
terraform init
terraform apply -var-file=terraform.tfvars
```

Operators write their own `terraform.tfvars`. The legacy `infra/terraform/terraform.tfvars.example` can serve as a starting reference for the AWS credentials block.

> **Note:** On first apply the LoadBalancer hostname may still be unresolved when Terraform reads the Service's `status` field; the `zap_url` output will contain `http://pending:8080`. Re-run `terraform apply` (or `terraform refresh`) once AWS finishes provisioning the ELB to populate the hostname.

## Outputs

`zap_namespace`, `zap_url`, `zap_api_key` (sensitive), `zap_api_key_secret_name` — feed `zap_url` and `zap_api_key` into the OWASP ZAP connector's secrets (`ZAP_URL`, `ZAP_API_KEY`); the namespace + secret name are useful for `kubectl` debugging.

## Teardown

```bash
cd src/connectors/owasp_zap/runtime
terraform destroy
```

The Deployment, Secret, LoadBalancer Service, and namespace are torn down cleanly. Caveats:

- The LoadBalancer Service's underlying AWS ELB is deprovisioned by the EKS cloud-controller-manager when the Service is deleted; Terraform does not manage it directly. If destroy succeeds but the ELB lingers, check the cloud-controller-manager logs in `kube-system`.
- The random API key is regenerated on the next apply — don't expect the same `ZAP_API_KEY` value after a destroy/apply cycle. Connector secrets that referenced the old key need to be re-written from the new `zap_api_key` output.

## Independence

This module references only operator-supplied inputs and the AWS / Kubernetes provider APIs. It does not depend on any other connector's runtime — per the redesign's no-inter-connector-dependency rule. The cross-runtime reference that previously came from `aws-foundation` outputs (`eks_cluster_name`) becomes an operator-supplied variable.

This module is intended to be used as a **root** module, not a child module. It declares its own `aws` and `kubernetes` provider blocks; using it via `module "..."` from a parent module will collide with the parent's providers.
