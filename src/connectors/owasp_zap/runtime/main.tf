# ---------------------------------------------------------------------------
# Provider configuration. Operator credentials are passed in as variables;
# Kubernetes auth is derived from EKS data sources (the original
# aws-foundation/scanners-eks split derived this from EKS data sources via
# module outputs, which we replicate here so the owasp_zap runtime is
# self-contained).
# ---------------------------------------------------------------------------

provider "aws" {
  region     = var.aws_region
  access_key = var.aws_access_key_id
  secret_key = var.aws_secret_access_key
}

data "aws_eks_cluster" "this" {
  name = var.eks_cluster_name
}

data "aws_eks_cluster_auth" "this" {
  name = var.eks_cluster_name
}

provider "kubernetes" {
  host                   = data.aws_eks_cluster.this.endpoint
  cluster_ca_certificate = base64decode(data.aws_eks_cluster.this.certificate_authority[0].data)
  token                  = data.aws_eks_cluster_auth.this.token
}

# ---------------------------------------------------------------------------
# ZAP Kubernetes namespace, secret (random API key), Deployment, and
# LoadBalancer Service. (Migrated from infra/terraform/modules/scanners-eks/
# main.tf — the ZAP slice only; the Semgrep / SonarQube / Juice Shop slices
# belong to other connectors' runtimes.)
#
# Unlike the Semgrep / SonarQube runtimes, ZAP has no IRSA, no S3 grant, and
# no IAM resources — it is a self-contained k8s daemon driven from outside
# (typically a CI workflow that triggers scans against a target URL via the
# ZAP API and then uploads the resulting report to the OWASP ZAP connector's
# ingestion path).
# ---------------------------------------------------------------------------

resource "kubernetes_namespace" "zap" {
  metadata { name = var.namespace_name }
}

resource "random_password" "zap_api_key" {
  length  = 40
  special = false
}

resource "kubernetes_secret" "zap_api_key" {
  metadata {
    name      = "zap-api-key"
    namespace = kubernetes_namespace.zap.metadata[0].name
  }
  data = { ZAP_API_KEY = random_password.zap_api_key.result }
}

resource "kubernetes_deployment" "zap" {
  metadata {
    name      = "zap"
    namespace = kubernetes_namespace.zap.metadata[0].name
  }
  spec {
    replicas = 1
    selector { match_labels = { app = "zap" } }
    template {
      metadata { labels = { app = "zap" } }
      spec {
        container {
          name  = "zap"
          image = var.zap_image
          command = ["zap.sh", "-daemon", "-host", "0.0.0.0", "-port", "8080",
            "-config", "api.key=$(ZAP_API_KEY)",
            "-config", "api.addrs.addr.name=.*",
          "-config", "api.addrs.addr.regex=true"]
          env_from {
            secret_ref {
              name = kubernetes_secret.zap_api_key.metadata[0].name
            }
          }
          port { container_port = 8080 }
        }
      }
    }
  }
}

resource "kubernetes_service" "zap" {
  metadata {
    name      = "zap"
    namespace = kubernetes_namespace.zap.metadata[0].name
  }
  spec {
    type     = "LoadBalancer"
    selector = { app = "zap" }
    port {
      port        = var.service_port
      target_port = 8080
    }
  }
}

data "kubernetes_service" "zap" {
  metadata {
    name      = kubernetes_service.zap.metadata[0].name
    namespace = kubernetes_namespace.zap.metadata[0].name
  }
  depends_on = [kubernetes_service.zap]
}
