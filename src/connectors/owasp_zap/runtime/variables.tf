# ---------------------------------------------------------------------------
# AWS-side inputs (operator-supplied; what aws-foundation used to produce
# internally before the redesign).
# ---------------------------------------------------------------------------

variable "aws_region" {
  description = "AWS region of the EKS cluster. Must match the region of `eks_cluster_name`."
  type        = string
}

variable "aws_access_key_id" {
  description = "AWS access key ID (operator-supplied)."
  type        = string
  sensitive   = true
}

variable "aws_secret_access_key" {
  description = "AWS secret access key (operator-supplied)."
  type        = string
  sensitive   = true
}

variable "project_prefix" {
  description = "Short slug used to namespace AWS resources (tags). The ZAP runtime is pure k8s and creates no AWS resources directly, but the LoadBalancer Service provisions an ELB in the cluster's account; tags on AWS-managed objects flow through here for consistency with the other scanner runtimes."
  type        = string
  default     = "appsec-mvp"
}

# ---------------------------------------------------------------------------
# EKS target — where the ZAP daemon Deployment + LoadBalancer Service run.
# ---------------------------------------------------------------------------

variable "eks_cluster_name" {
  description = "Operator-supplied EKS cluster name. The ZAP namespace, Deployment, Secret, and LoadBalancer Service are created in this cluster. Must be in `var.aws_region` — the kubernetes provider's auth flow resolves the cluster endpoint via the AWS provider's region."
  type        = string
}

# ---------------------------------------------------------------------------
# ZAP daemon configuration.
# ---------------------------------------------------------------------------

variable "namespace_name" {
  description = "Kubernetes namespace for the ZAP daemon Deployment, Secret, and Service."
  type        = string
  default     = "zap"
}

variable "zap_image" {
  description = "Container image used by the ZAP daemon Deployment. Captured as a variable for reproducibility — the source module hard-coded `owasp/zap2docker-stable:2.14.0`."
  type        = string
  default     = "owasp/zap2docker-stable:2.14.0"
}

variable "service_port" {
  description = "Port exposed by the LoadBalancer Service and the ZAP container. The ZAP daemon listens on 8080 by default; if you override this, the daemon's `-port` arg in the Deployment command stays at 8080 and the Service's `target_port` follows suit — only the public-facing `port` changes."
  type        = number
  default     = 8080
}
