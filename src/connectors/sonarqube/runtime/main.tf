# ---------------------------------------------------------------------------
# Provider configuration. Operator credentials are passed in as variables;
# Kubernetes / Helm auth is derived from EKS data sources (the original
# aws-foundation/scanners-eks split derived this from EKS data sources via
# module outputs, which we replicate here so the sonarqube runtime is
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

provider "helm" {
  kubernetes {
    host                   = data.aws_eks_cluster.this.endpoint
    cluster_ca_certificate = base64decode(data.aws_eks_cluster.this.certificate_authority[0].data)
    token                  = data.aws_eks_cluster_auth.this.token
  }
}

# ---------------------------------------------------------------------------
# RDS Postgres backing store for SonarQube. Conditional: created only when
# the operator did not supply a pre-existing `rds_endpoint`.
# (Migrated from infra/terraform/modules/aws-foundation/main.tf — the
# `rds_sonarqube` module + supporting subnet group + security group + random
# password.)
# ---------------------------------------------------------------------------

locals {
  create_rds = var.rds_endpoint == ""

  rds_endpoint_resolved = local.create_rds ? aws_db_instance.sonarqube[0].endpoint : var.rds_endpoint
  rds_username_resolved = local.create_rds ? aws_db_instance.sonarqube[0].username : var.rds_username
  rds_password_resolved = local.create_rds ? random_password.rds[0].result : var.rds_password
  rds_db_name_resolved  = local.create_rds ? aws_db_instance.sonarqube[0].db_name : var.rds_db_name
}

resource "random_password" "rds" {
  count   = local.create_rds ? 1 : 0
  length  = 32
  special = false
}

resource "aws_db_subnet_group" "sonarqube" {
  count      = local.create_rds ? 1 : 0
  name       = "${var.project_prefix}-rds"
  subnet_ids = var.vpc_subnet_ids
}

resource "aws_security_group" "rds" {
  count       = local.create_rds ? 1 : 0
  name        = "${var.project_prefix}-rds"
  description = "Allow Postgres traffic from the EKS VPC"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr_block]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_db_instance" "sonarqube" {
  count = local.create_rds ? 1 : 0

  identifier = "${var.project_prefix}-sonarqube"

  engine            = "postgres"
  engine_version    = var.rds_engine_version
  instance_class    = var.rds_instance_class
  allocated_storage = var.rds_allocated_storage

  db_name  = var.rds_db_name
  username = var.rds_username
  password = random_password.rds[0].result
  port     = 5432

  vpc_security_group_ids = [aws_security_group.rds[0].id]
  db_subnet_group_name   = aws_db_subnet_group.sonarqube[0].name

  parameter_group_name = "default.${var.rds_parameter_group_family}"

  skip_final_snapshot = true
  deletion_protection = false
}

# ---------------------------------------------------------------------------
# SonarQube Kubernetes namespace + JDBC secret + Helm release.
# (Migrated from infra/terraform/modules/scanners-eks/main.tf — the SonarQube
# slice only; the Semgrep / ZAP / Juice Shop slices belong to other
# connectors' runtimes.)
# ---------------------------------------------------------------------------

resource "kubernetes_namespace" "sonarqube" {
  metadata {
    name = var.sonarqube_namespace
  }
}

resource "kubernetes_secret" "sonarqube_db" {
  metadata {
    name      = "sonarqube-db"
    namespace = kubernetes_namespace.sonarqube.metadata[0].name
  }
  data = {
    jdbcUrl      = "jdbc:postgresql://${local.rds_endpoint_resolved}/${local.rds_db_name_resolved}"
    jdbcUsername = local.rds_username_resolved
    jdbcPassword = local.rds_password_resolved
  }
}

resource "helm_release" "sonarqube" {
  name       = "sonarqube"
  repository = "https://SonarSource.github.io/helm-chart-sonarqube"
  chart      = "sonarqube"
  version    = var.sonarqube_chart_version
  namespace  = kubernetes_namespace.sonarqube.metadata[0].name

  values = [yamlencode({
    postgresql = { enabled = false }
    jdbcOverwrite = {
      enable                = true
      jdbcUrl               = "jdbc:postgresql://${local.rds_endpoint_resolved}/${local.rds_db_name_resolved}"
      jdbcUsername          = local.rds_username_resolved
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

# ---------------------------------------------------------------------------
# Long-lived project analysis token. The Sonar Helm chart does not support
# declarative token creation, so this module emits a random opaque value
# that operators register with SonarQube post-install (or surface to the
# cross-scanner CI workflow as `sonarqube_project_token`). Preserved
# verbatim from the source module.
# ---------------------------------------------------------------------------

resource "random_password" "sonarqube_token" {
  length  = 40
  special = false
}
