# OWASP ZAP connector: source system runtime (optional)

This Terraform module deploys an **OWASP ZAP daemon** on the EKS cluster of the user, exposed via a LoadBalancer Service. The OWASP ZAP connector then drives the daemon (typically from a CI workflow that triggers scans against a target URL via the ZAP API) and ingests the resulting findings.

**It is optional.** The OWASP ZAP connector itself only needs a ZAP daemon URL and API key. Users with their own ZAP deployment skip this module entirely and feed their existing endpoint directly into the secrets of the connector.

## When to apply

Apply this module if you want appsec-mvp to provision a ZAP daemon on your EKS cluster. Skip it if you have your own ZAP instance. In that case wire the URL and API key of the existing daemon into the OWASP ZAP connector secrets directly.

## What it creates

- A `zap` Kubernetes namespace on your EKS cluster.
- A random 40 character ZAP API key, stored in a kubernetes secret as the `ZAP_API_KEY` env var.
- A ZAP Deployment (`replicas = 1`) running `owasp/zap2docker-stable:2.14.0` in daemon mode on container port 8080. The container command is `zap.sh -daemon -host 0.0.0.0 -port 8080 -config api.key=$(ZAP_API_KEY) -config api.addrs.addr.name=.* -config api.addrs.addr.regex=true` (faithful to the source module).
- A LoadBalancer Service exposing the daemon publicly on `var.service_port` (default `8080`). The `zap_url` output gives the resulting public URL.

The runtime is pure Kubernetes. No IRSA, no IAM role, no S3 grants. (The LoadBalancer Service does cause AWS to provision an ELB on behalf of the cluster, but that is managed transparently by the EKS cloud-controller-manager, not by this module.)

> **Security note:** the Deployment runs ZAP with `api.addrs.addr.name=.*` + `api.addrs.addr.regex=true`, which whitelists *all caller IPs* against the ZAP API. Combined with the public LoadBalancer Service, this means the API of the daemon is internet facing and the only access control is the 40 character random API key. This is faithful to the upstream demo configuration. **Production deployments should front the daemon with a Kubernetes NetworkPolicy, a private (`internal`-mode) LoadBalancer, or a VPN gateway**, and consider tightening `api.addrs.addr.*` to a specific caller IP or range.

## User supplied inputs

### Required

| Variable | Description |
|---|---|
| `aws_region` | AWS region of the EKS cluster. Must match the region of `eks_cluster_name`. |
| `aws_access_key_id`, `aws_secret_access_key` | AWS credentials (sensitive). |
| `eks_cluster_name` | EKS cluster where the ZAP daemon is installed. Must be in `var.aws_region`. |

### Optional

| Variable | Description | Default |
|---|---|---|
| `project_prefix` | Tag and name prefix for AWS resources. | `appsec-mvp` |
| `namespace_name` | Kubernetes namespace name. | `zap` |
| `zap_image` | Container image used by the Deployment. Captured as a variable for reproducibility. The source module hard coded the `2.14.0` tag. | `owasp/zap2docker-stable:2.14.0` |
| `service_port` | Public port on the LoadBalancer Service. The container port of the daemon stays at 8080. Only the externally exposed Service port changes. | `8080` |

## Apply

```bash
cd src/connectors/owasp_zap/runtime
terraform init
terraform apply -var-file=terraform.tfvars
```

Or use the bundled `install.sh` wrapper, which reads the AWS / EKS credentials from the environment (`AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `EKS_CLUSTER_NAME` — and the optional `NAMESPACE_NAME`, `ZAP_IMAGE`, `SERVICE_PORT` overrides) and runs `terraform init` + `terraform apply -auto-approve`.

> **Note:** On first apply the LoadBalancer hostname may still be unresolved when Terraform reads the `status` field of the Service. The `zap_url` output will contain `http://pending:8080`. Re-run `terraform apply` (or `terraform refresh`) once AWS finishes provisioning the ELB to populate the hostname.

## Outputs

`zap_namespace`, `zap_url`, `zap_api_key` (sensitive), `zap_api_key_secret_name`. Feed `zap_url` and `zap_api_key` into the OWASP ZAP connector secrets (`ZAP_URL`, `ZAP_API_KEY`). The namespace and secret name are useful for `kubectl` debugging.

## Teardown

```bash
cd src/connectors/owasp_zap/runtime
terraform destroy
```

The Deployment, Secret, LoadBalancer Service, and namespace are torn down cleanly. Caveats:

- The underlying AWS ELB of the LoadBalancer Service is deprovisioned by the EKS cloud-controller-manager when the Service is deleted. Terraform does not manage it directly. If destroy succeeds but the ELB lingers, check the cloud-controller-manager logs in `kube-system`.
- The random API key is regenerated on the next apply. Do not expect the same `ZAP_API_KEY` value after a destroy and apply cycle. Connector secrets that referenced the old key need to be re-written from the new `zap_api_key` output.

## Independence

This module references only user supplied inputs and the AWS and Kubernetes provider APIs. It does not depend on the runtime of any other connector, per the no inter connector dependency rule of the redesign. The cross-runtime reference that previously came from `aws-foundation` outputs (`eks_cluster_name`) becomes an user supplied variable.

This module is intended to be used as a **root** module, not a child module. It declares its own `aws` and `kubernetes` provider blocks. Using it via `module "..."` from a parent module will collide with the providers of the parent.
