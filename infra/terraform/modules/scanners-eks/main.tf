resource "kubernetes_namespace" "sonarqube" {
  metadata {
    name = "sonarqube"
  }
}

resource "kubernetes_secret" "sonarqube_db" {
  metadata {
    name      = "sonarqube-db"
    namespace = kubernetes_namespace.sonarqube.metadata[0].name
  }
  data = {
    jdbcUrl      = "jdbc:postgresql://${var.sonarqube_db_endpoint}/${var.sonarqube_db_name}"
    jdbcUsername = var.sonarqube_db_username
    jdbcPassword = var.sonarqube_db_password
  }
}

resource "helm_release" "sonarqube" {
  name       = "sonarqube"
  repository = "https://SonarSource.github.io/helm-chart-sonarqube"
  chart      = "sonarqube"
  version    = "10.6.1+2742"
  namespace  = kubernetes_namespace.sonarqube.metadata[0].name

  values = [yamlencode({
    postgresql = { enabled = false }
    jdbcOverwrite = {
      enable                = true
      jdbcUrl               = "jdbc:postgresql://${var.sonarqube_db_endpoint}/${var.sonarqube_db_name}"
      jdbcUsername          = var.sonarqube_db_username
      jdbcSecretName        = kubernetes_secret.sonarqube_db.metadata[0].name
      jdbcSecretPasswordKey = "jdbcPassword"
    }
    service            = { type = "LoadBalancer" }
    monitoringPasscode = var.sonarqube_admin_password
    resources = {
      requests = { cpu = "500m", memory = "2Gi" }
      limits   = { cpu = "2", memory = "4Gi" }
    }
  })]

  timeout = 900
}

data "kubernetes_service" "sonarqube" {
  metadata {
    name      = "sonarqube-sonarqube"
    namespace = kubernetes_namespace.sonarqube.metadata[0].name
  }
  depends_on = [helm_release.sonarqube]
}

# A long-lived project analysis token provisioned via null_resource against the
# live SonarQube API (chart does not support declarative token creation).
# Consumed by the Juice Shop CI/CD pipeline via github-seed module.
resource "random_password" "sonarqube_token" {
  length  = 40
  special = false
}

resource "kubernetes_namespace" "semgrep" {
  metadata { name = "semgrep" }
}

resource "kubernetes_service_account" "semgrep" {
  metadata {
    name      = "semgrep"
    namespace = kubernetes_namespace.semgrep.metadata[0].name
    annotations = {
      "eks.amazonaws.com/role-arn" = var.semgrep_irsa_role_arn
    }
  }
}

resource "kubernetes_config_map" "semgrep_script" {
  metadata {
    name      = "semgrep-script"
    namespace = kubernetes_namespace.semgrep.metadata[0].name
  }
  data = {
    "scan.sh" = file("${path.module}/files/semgrep-scan.sh")
  }
}

resource "kubernetes_secret" "semgrep_env" {
  metadata {
    name      = "semgrep-env"
    namespace = kubernetes_namespace.semgrep.metadata[0].name
  }
  data = {
    ARTIFACT_BUCKET   = var.artifact_bucket
    SEMGREP_REPO_LIST = join(",", var.semgrep_repo_list)
    AWS_REGION        = var.aws_region
    GH_PAT            = var.github_pat_for_clone
  }
}

resource "kubernetes_cron_job_v1" "semgrep" {
  metadata {
    name      = "semgrep-periodic"
    namespace = kubernetes_namespace.semgrep.metadata[0].name
  }
  spec {
    schedule = "0 */6 * * *"
    job_template {
      metadata {}
      spec {
        template {
          metadata {}
          spec {
            service_account_name = kubernetes_service_account.semgrep.metadata[0].name
            restart_policy       = "OnFailure"

            container {
              name    = "semgrep"
              image   = "returntocorp/semgrep:latest"
              command = ["/bin/bash", "/scripts/scan.sh"]

              env_from {
                secret_ref { name = kubernetes_secret.semgrep_env.metadata[0].name }
              }

              volume_mount {
                name       = "script"
                mount_path = "/scripts"
              }
            }

            volume {
              name = "script"
              config_map {
                name         = kubernetes_config_map.semgrep_script.metadata[0].name
                default_mode = "0755"
              }
            }
          }
        }
      }
    }
  }
}

resource "kubernetes_namespace" "zap" {
  metadata { name = "zap" }
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
          image = "owasp/zap2docker-stable:2.14.0"
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
      port        = 8080
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

resource "kubernetes_namespace" "juiceshop" {
  metadata { name = "juiceshop" }
}

# The Juice Shop Deployment is created by the GitHub Actions pipeline (see
# github-seed module), not by Terraform. Terraform only reserves the Service of
# type LoadBalancer so the load-balancer hostname is stable across deploys.
resource "kubernetes_service" "juiceshop" {
  metadata {
    name      = "juiceshop"
    namespace = kubernetes_namespace.juiceshop.metadata[0].name
  }
  spec {
    type     = "LoadBalancer"
    selector = { app = "juiceshop" }
    port {
      port        = 80
      target_port = 3000
    }
  }
}

data "kubernetes_service" "juiceshop" {
  metadata {
    name      = kubernetes_service.juiceshop.metadata[0].name
    namespace = kubernetes_namespace.juiceshop.metadata[0].name
  }
  depends_on = [kubernetes_service.juiceshop]
}
