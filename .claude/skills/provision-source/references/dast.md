# provision-source — dast reference

DAST connectors split into two sub-shapes:

1. **Daemon** (canonical follower at `a086f9d:src/connectors/owasp_zap/runtime/`). Deploys an OWASP ZAP daemon container on EKS via a Deployment + LoadBalancer Service, with a random API key stored in a Kubernetes Secret. The daemon is driven from outside (typically a CI workflow that triggers scans against a target URL via the ZAP API). Provider stack: `aws` + `kubernetes` + `random`. Note: there is no live DAST follower currently — this sub-shape is reverse-engineered from the pre-deletion `a086f9d` state and is restored greenfield in Phase 3.

2. **CI/CD-step** (no canonical follower yet — described as the reference shape for connectors where the operator runs the scanner inline in a CI pipeline). Provider: `hashicorp/null` only. The runtime is a no-op smoke-test placeholder; `runtime/install.sh` prints the operator-facing setup-already-done message. The connector page documents how the operator configures their CI pipeline to run the scanner.

The auto-deriver chooses the sub-shape based on whether `runtime/main.tf` contains `kubernetes_deployment` (daemon) or only a `terraform_data` no-op (CI/CD-step).

## operational.yml.source_runtime schema

Common fields:

| Field | Type | Required | Default | Source-of-derivation |
|---|---|---|---|---|
| `runtime_provisioner` | string (enum: `terraform-aws-eks-daemon`, `terraform-null-cicd-step`) | yes | — | inferred from `runtime/main.tf`: `kubernetes_deployment` present → daemon; only `terraform_data` no-op → cicd-step |
| `terraform_required_version` | string | no | `>= 1.7` | `runtime/versions.tf` |

Additional fields when `runtime_provisioner = terraform-aws-eks-daemon` (owasp_zap pattern):

| Field | Type | Required | Default | Source-of-derivation |
|---|---|---|---|---|
| `aws_region_var_name` | string | yes | `aws_region` | `runtime/variables.tf` |
| `eks_cluster_name_var_name` | string | yes | `eks_cluster_name` | `runtime/variables.tf` |
| `project_prefix_default` | string | no | `appsec-mvp` | `runtime/variables.tf` `variable "project_prefix" { default = ... }` |
| `namespace_default` | string | no | `zap` | `runtime/variables.tf` `variable "namespace_name" { default = ... }` |
| `daemon_image_default` | string | yes | `owasp/zap2docker-stable:2.14.0` | `runtime/variables.tf` `variable "{source}_image" { default = ... }` |
| `service_port_default` | number | no | `8080` | `runtime/variables.tf` `variable "service_port" { default = ... }` |
| `container_port` | number | no | `8080` | `runtime/main.tf` `kubernetes_deployment.{source}` container `port { container_port = ... }` |
| `daemon_command` | list[string] | yes | full ZAP daemon argv (`["zap.sh", "-daemon", "-host", "0.0.0.0", "-port", "8080", "-config", "api.key=$(ZAP_API_KEY)", "-config", "api.addrs.addr.name=.*", "-config", "api.addrs.addr.regex=true"]`) | `runtime/main.tf` `kubernetes_deployment.{source}` `container.command` |
| `api_key_length` | number | no | `40` | `runtime/main.tf` `random_password.{source}_api_key.length` |
| `api_key_secret_name` | string | yes | `{source}-api-key` | `runtime/main.tf` `kubernetes_secret.{source}_api_key.metadata.name` |
| `api_key_env_var_name` | string | yes | `ZAP_API_KEY` | `runtime/main.tf` `kubernetes_secret.{source}_api_key.data` key |

Additional fields when `runtime_provisioner = terraform-null-cicd-step` (CI/CD-step):

| Field | Type | Required | Default | Source-of-derivation |
|---|---|---|---|---|
| `ci_step_setup_message` | string | yes | — | operator-supplied message printed by `runtime/install.sh` |
| `ci_workflow_pointers` | list[string] | no | `["./examples/end-to-end-demo/.github/workflows/scan.yml"]` | operator-supplied; pages reference these for CI integration examples |

## Terraform shape

### Sub-shape A: daemon (owasp_zap pattern)

**Provider declarations** (`runtime/versions.tf`):

```hcl
terraform {
  required_version = ">= 1.7"
  required_providers {
    aws        = { source = "hashicorp/aws", version = "~> 5.0" }
    kubernetes = { source = "hashicorp/kubernetes", version = "~> 2.30" }
    random     = { source = "hashicorp/random", version = "~> 3.6" }
  }
}
```

**Modules referenced:** none — pure k8s + random; no IAM, no IRSA.

**Resources created:**
- `data.aws_eks_cluster` + `data.aws_eks_cluster_auth` — EKS auth handoff.
- `kubernetes_namespace.{source}` — the daemon namespace.
- `random_password.{source}_api_key` (length 40, special=false) — the API key for authenticating callers to the daemon's REST API.
- `kubernetes_secret.{source}_api_key` — wraps the API key as the `ZAP_API_KEY` env var injected via `env_from.secret_ref`.
- `kubernetes_deployment.{source}` — `replicas = 1`, runs the daemon image with the full argv `["zap.sh", "-daemon", "-host", "0.0.0.0", "-port", "8080", "-config", "api.key=$(ZAP_API_KEY)", "-config", "api.addrs.addr.name=.*", "-config", "api.addrs.addr.regex=true"]`.
- `kubernetes_service.{source}` — `type = LoadBalancer`, exposes the daemon publicly on `var.service_port`.
- `data.kubernetes_service.{source}` (depends_on the LoadBalancer Service) — used by outputs to read the LoadBalancer ingress hostname after AWS provisions the ELB.

**Variables exposed:**

| Name | Type | Sensitive | Required | Default |
|---|---|---|---|---|
| `aws_region` | string | no | yes | — |
| `aws_access_key_id` | string | yes | yes | — |
| `aws_secret_access_key` | string | yes | yes | — |
| `project_prefix` | string | no | no | `appsec-mvp` |
| `eks_cluster_name` | string | no | yes | — |
| `namespace_name` | string | no | no | `zap` |
| `{source}_image` | string | no | no | `owasp/zap2docker-stable:2.14.0` |
| `service_port` | number | no | no | `8080` |

**Outputs:**

| Name | Description |
|---|---|
| `{source}_namespace` | Kubernetes namespace where the daemon runs |
| `{source}_url` | `http://<lb-hostname>:<service_port>` (may be `pending` on first apply; re-run `terraform apply` once AWS provisions the ELB) |
| `{source}_api_key` (sensitive) | API key for authenticating to the daemon |
| `{source}_api_key_secret_name` | Name of the kubernetes secret holding the API key |

> **Security note:** the Deployment runs the daemon with `api.addrs.addr.name=.*` + `api.addrs.addr.regex=true`, which whitelists *all caller IPs* against the daemon's API. Combined with the public LoadBalancer Service, the daemon API is internet-facing and the only access control is the 40-character random API key. **Production deployments should front the daemon with a Kubernetes NetworkPolicy, a private (`internal`-mode) LoadBalancer, or a VPN gateway**, and consider tightening `api.addrs.addr.*` to a specific caller IP or range.

### Sub-shape B: CI/CD-step

**Provider declarations** (`runtime/versions.tf`):

```hcl
terraform {
  required_version = ">= 1.7"
  required_providers {
    null = { source = "hashicorp/null", version = "~> 3.2" }
  }
}
```

**Modules referenced:** none.

**Resources:** a single `terraform_data` (or `null_resource`) no-op sentinel that prints the setup-already-done message at apply time. The runtime is a placeholder for structural parity; `runtime/install.sh` prints the operator-facing message that DAST scanning is configured at the CI/CD step layer (e.g. `zap-baseline.py` step in a GitHub Actions workflow), and the connector page documents how to wire it.

**Variables:** none (or a single optional `project_prefix` for parity).

**Outputs:** none, or a `cicd_step_pointer` echoing the documented workflow path.

## runtime/files/* conventions

Sub-shape A (daemon, owasp_zap): no `runtime/files/*` by default. The daemon image and command line are baked into `main.tf`. If an operator wants to bind-mount a custom `zap.policies` or context file, the sidecar would live at `runtime/files/zap-context.xml` and be loaded via a ConfigMap in `main.tf`.

Sub-shape B (CI/CD-step): no `runtime/files/*`. CI workflow YAML lives in `examples/end-to-end-demo/.github/workflows/scan.yml`, **outside** the connector tree, because it spans multiple connectors.

## runtime/install.sh template

```bash
#!/usr/bin/env bash
# Source-side install for the {source} {category} runtime.
#
# Sub-shape: {runtime_provisioner}
{if runtime_provisioner == terraform-aws-eks-daemon}
#
# This runtime deploys a {source} daemon container on EKS via a Deployment +
# LoadBalancer Service, with a random API key stored in a Kubernetes Secret.
#
# Required environment variables (consumed by terraform via TF_VAR_*):
#   AWS_REGION              — must match the region of $EKS_CLUSTER_NAME
#   AWS_ACCESS_KEY_ID       — sensitive
#   AWS_SECRET_ACCESS_KEY   — sensitive
#   EKS_CLUSTER_NAME        — EKS cluster where the daemon runs
#
# Optional:
#   NAMESPACE_NAME          — default: {namespace_default}
#   {source_upper}_IMAGE    — default: {daemon_image_default}
#   SERVICE_PORT            — default: {service_port_default}
{else if runtime_provisioner == terraform-null-cicd-step}
#
# This runtime is a no-op placeholder. {source} runs at the CI/CD step layer
# (see {ci_workflow_pointers}); there is no source-side infrastructure for
# Terraform to provision. The runtime exists for structural parity with the
# other connectors' runtimes.
{end}
#
# Idempotent: re-runs reconcile state with the AWS / EKS side (or print the
# placeholder message in the CI/CD-step sub-shape).

set -euo pipefail
{if runtime_provisioner == terraform-aws-eks-daemon}

: "${AWS_REGION:?AWS_REGION is required}"
: "${AWS_ACCESS_KEY_ID:?AWS_ACCESS_KEY_ID is required}"
: "${AWS_SECRET_ACCESS_KEY:?AWS_SECRET_ACCESS_KEY is required}"
: "${EKS_CLUSTER_NAME:?EKS_CLUSTER_NAME is required}"

export TF_VAR_aws_region="${AWS_REGION}"
export TF_VAR_aws_access_key_id="${AWS_ACCESS_KEY_ID}"
export TF_VAR_aws_secret_access_key="${AWS_SECRET_ACCESS_KEY}"
export TF_VAR_eks_cluster_name="${EKS_CLUSTER_NAME}"
[[ -n "${NAMESPACE_NAME:-}" ]] && export TF_VAR_namespace_name="${NAMESPACE_NAME}"
[[ -n "${{source_upper}_IMAGE:-}" ]] && export TF_VAR_{source}_image="${{source_upper}_IMAGE}"
[[ -n "${SERVICE_PORT:-}" ]] && export TF_VAR_service_port="${SERVICE_PORT}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
cd "${SCRIPT_DIR}"

terraform init -input=false
terraform apply -input=false -auto-approve

echo "OK: {source} source-side runtime apply complete."
echo "Outputs:"
terraform output
echo
echo "Note: on first apply the LoadBalancer hostname may still be unresolved"
echo "      ({source}_url shows 'http://pending:...'). Re-run 'terraform apply'"
echo "      once AWS finishes provisioning the ELB to populate the hostname."
{else if runtime_provisioner == terraform-null-cicd-step}

cat <<'MSG'
{source} runs at the CI/CD step layer — there is no source-side
infrastructure to provision via Terraform.

{ci_step_setup_message}

For an end-to-end CI example, see:
{ci_workflow_pointers each as "  - <pointer>"}

Proceed to the connector's Secrets section to wire the scan output into the
Databricks-side ingestion pipeline.
MSG

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
cd "${SCRIPT_DIR}"
terraform init -input=false
terraform apply -input=false -auto-approve

echo "OK: {source} runtime smoke-test placeholder applied."
{end}
```

## runtime/README.md template

```markdown
# {source} connector: source system runtime (optional)

{if runtime_provisioner == terraform-aws-eks-daemon}
This Terraform module deploys an **{source} daemon** on the EKS cluster of the user, exposed via a LoadBalancer Service. The {source} connector then drives the daemon (typically from a CI workflow that triggers scans against a target URL via the daemon's API) and ingests the resulting findings.
{else if runtime_provisioner == terraform-null-cicd-step}
This Terraform module is a **no-op placeholder**. {source} runs at the CI/CD step layer (e.g. a `{source}-baseline.py` step in a GitHub Actions workflow). There is no source-side infrastructure to provision; this module exists for structural parity with the other connectors.
{end}

**It is optional.** {if daemon}The {source} connector itself only needs a daemon URL and API key. Users with their own deployment skip this module entirely.{else}There is nothing to apply on the source side; the runtime is documentation and parity only.{end}

## When to apply

{if daemon}
Apply this module if you want appsec-mvp to provision a {source} daemon on your EKS cluster. Skip it if you have your own instance — wire the URL and API key directly into the connector secrets.
{else}
Apply this module to confirm structural parity (the apply prints the CI/CD setup message and exits cleanly). Skip if you do not need that confirmation.
{end}

## What it creates

{if daemon}
- A `{namespace_default}` Kubernetes namespace on your EKS cluster.
- A random {api_key_length}-character API key stored in a kubernetes secret as the `{api_key_env_var_name}` env var.
- A Deployment (`replicas = 1`) running `{daemon_image_default}` in daemon mode on container port {container_port}. The container command is the canonical daemon argv with `api.key=$({api_key_env_var_name})` and `api.addrs.addr.{name,regex}=...`.
- A LoadBalancer Service exposing the daemon publicly on `var.service_port` (default `{service_port_default}`).

The runtime is pure Kubernetes. No IRSA, no IAM role, no S3 grants. (The LoadBalancer Service does cause AWS to provision an ELB on behalf of the cluster, but that is managed transparently by the EKS cloud-controller-manager, not by this module.)

> **Security note:** the Deployment runs the daemon with `api.addrs.addr.name=.*` + `api.addrs.addr.regex=true`, which whitelists *all caller IPs*. The daemon API is internet-facing and the only access control is the {api_key_length}-character random API key. **Production deployments should front the daemon with a Kubernetes NetworkPolicy, a private (`internal`-mode) LoadBalancer, or a VPN gateway**, and consider tightening `api.addrs.addr.*` to a specific caller IP or range.
{else}
A single `terraform_data` no-op sentinel that prints the CI/CD setup message at apply time and exits cleanly.
{end}

## User-supplied inputs

{if daemon}
### Required

| Variable | Description |
|---|---|
| `aws_region` | AWS region of the EKS cluster. Must match the region of `eks_cluster_name`. |
| `aws_access_key_id`, `aws_secret_access_key` | AWS credentials (sensitive). |
| `eks_cluster_name` | EKS cluster where the daemon is installed. |

### Optional

| Variable | Description | Default |
|---|---|---|
| `project_prefix` | Tag and name prefix for AWS resources. | `{project_prefix_default}` |
| `namespace_name` | Kubernetes namespace name. | `{namespace_default}` |
| `{source}_image` | Container image used by the Deployment. | `{daemon_image_default}` |
| `service_port` | Public port on the LoadBalancer Service. The container port stays at {container_port}. | `{service_port_default}` |
{else}
None (or `project_prefix` only, for parity).
{end}

## Apply

```bash
cd src/connectors/{source}/runtime
terraform init
terraform apply -var-file=terraform.tfvars
```

Or use the bundled `install.sh` wrapper.

{if daemon}
> **Note:** On first apply the LoadBalancer hostname may still be unresolved when Terraform reads the Service's `status` field. The `{source}_url` output will contain `http://pending:{service_port_default}`. Re-run `terraform apply` (or `terraform refresh`) once AWS finishes provisioning the ELB.
{end}

## Outputs

{if daemon}
`{source}_namespace`, `{source}_url`, `{source}_api_key` (sensitive), `{source}_api_key_secret_name`. Feed `{source}_url` and `{source}_api_key` into the connector secrets. The namespace and secret name are useful for `kubectl` debugging.
{else}
None.
{end}

## Teardown

```bash
cd src/connectors/{source}/runtime
terraform destroy
```

{if daemon}
The Deployment, Secret, LoadBalancer Service, and namespace are torn down cleanly. Caveats:

- The underlying AWS ELB is deprovisioned by the EKS cloud-controller-manager when the Service is deleted. Terraform does not manage it directly. If destroy succeeds but the ELB lingers, check the cloud-controller-manager logs in `kube-system`.
- The random API key is regenerated on the next apply. Connector secrets that referenced the old key need to be re-written from the new `{source}_api_key` output.
{else}
The placeholder destroy is a no-op.
{end}

## Independence

This module references only user-supplied inputs and the AWS{if daemon} and Kubernetes{end} provider APIs. It does not depend on the runtime of any other connector, per the no-inter-connector-dependency rule of the redesign.

This module is intended to be used as a **root** module, not a child module. It declares its own provider blocks. Using it via `module "..."` from a parent module will collide with the providers of the parent.
```

## Page §Source provisioning section template

Inserted after `## User inputs` and before `## Secrets`. Section heading: `## Optional source runtime`.

```markdown
## Optional source runtime

{if runtime_provisioner == terraform-aws-eks-daemon}
The Terraform module under [`src/connectors/{source}/runtime/`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/{source}/runtime) deploys an **{source} daemon container** on an existing EKS cluster, exposed via a LoadBalancer Service on port {service_port_default}, with a random {api_key_length}-character API key stored in a Kubernetes Secret. Users with their own {source} deployment skip this entirely and feed their existing endpoint directly into the connector secrets.

Required runtime inputs at a glance: `aws_region`, `aws_access_key_id`, `aws_secret_access_key`, `eks_cluster_name`. Optional: `namespace_name` (default `{namespace_default}`), `{source}_image` (default `{daemon_image_default}`), `service_port` (default `{service_port_default}`).

Apply with:

```bash
cd src/connectors/{source}/runtime
terraform init
terraform apply -var-file=terraform.tfvars
```

> **Security note:** the daemon ships with `api.addrs.addr.name=.*` + `api.addrs.addr.regex=true` (all caller IPs whitelisted), and the Service is `type = LoadBalancer` (public). The only access control is the random API key. **Production deployments should front the daemon with a NetworkPolicy, a private LoadBalancer, or a VPN gateway**, and consider tightening `api.addrs.addr.*` to a specific caller IP or range.

On first apply, the `{source}_url` output may report `http://pending:{service_port_default}` while AWS is still provisioning the ELB. Re-run `terraform apply` once the LoadBalancer hostname resolves.
{else if runtime_provisioner == terraform-null-cicd-step}
The runtime under [`src/connectors/{source}/runtime/`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/{source}/runtime) is a **no-op placeholder**. {source} runs at the CI/CD step layer; there is no source-side infrastructure to provision via Terraform. The placeholder exists for structural parity.

CI integration is operator-authored. See `examples/end-to-end-demo/.github/workflows/scan.yml` for a reference workflow that runs `{source}` and uploads the scan report to the path the connector ingests from.

Apply (smoke-test):

```bash
cd src/connectors/{source}/runtime
terraform init
terraform apply
```

The apply prints the setup message and exits. Proceed to **Secrets** to wire the scan output into the Databricks-side pipeline.
{end}

See [`runtime/README.md`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/{source}/runtime) for the full variable list and override flags.
```
