# ---------------------------------------------------------------------------
# AWS-side inputs (operator-supplied; what aws-foundation used to produce
# internally before the redesign).
# ---------------------------------------------------------------------------

variable "aws_region" {
  description = "AWS region for EKS + (optional) RDS. Must match the region of `eks_cluster_name`."
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
  description = "Short slug used to namespace AWS resources (RDS identifier, security group name, subnet group name)."
  type        = string
  default     = "appsec-mvp"
}

# ---------------------------------------------------------------------------
# EKS target — where SonarQube is installed.
# ---------------------------------------------------------------------------

variable "eks_cluster_name" {
  description = "Operator-supplied EKS cluster name. The SonarQube namespace, Helm release, and JDBC secret are created in this cluster. Must be in `var.aws_region` — the kubernetes provider's auth flow resolves the cluster endpoint via the AWS provider's region."
  type        = string
}

# ---------------------------------------------------------------------------
# SonarQube admin / monitoring credentials.
# ---------------------------------------------------------------------------

variable "sonarqube_admin_password" {
  description = "Initial value applied to both the SonarQube admin web-UI password (account.adminPassword) and the JMX-style monitoring passcode. Sensitive."
  type        = string
  sensitive   = true
}

# ---------------------------------------------------------------------------
# RDS Postgres backing store. By default the module creates its own RDS
# instance for SonarQube. Operators with an existing Postgres database can
# set `rds_endpoint` (plus credentials) to skip RDS creation.
# ---------------------------------------------------------------------------

variable "rds_endpoint" {
  description = "(Optional) Pre-existing Postgres endpoint (host:port) for SonarQube's backing store. When empty, this module creates its own RDS instance."
  type        = string
  default     = ""
}

variable "rds_db_name" {
  description = "Postgres database name SonarQube uses. Used both when creating RDS and when targeting an operator-supplied endpoint."
  type        = string
  default     = "sonar"
}

variable "rds_username" {
  description = "(Optional) Postgres username — used both when creating RDS (master username) and when targeting an operator-supplied endpoint."
  type        = string
  default     = "sonar"
}

variable "rds_password" {
  description = "(Optional) Postgres password. Required when `rds_endpoint` is non-empty. When `rds_endpoint` is empty (this module creates RDS), leave blank — a random password is generated. Sensitive."
  type        = string
  sensitive   = true
  default     = ""
}

variable "rds_instance_class" {
  description = "RDS instance class used when this module creates the database."
  type        = string
  default     = "db.t3.small"
}

variable "rds_allocated_storage" {
  description = "RDS allocated storage (GiB) used when this module creates the database."
  type        = number
  default     = 20
}

variable "rds_engine_version" {
  description = "Postgres engine version used when this module creates the database."
  type        = string
  default     = "15"
}

variable "rds_parameter_group_family" {
  description = "RDS parameter group family used when this module creates the database."
  type        = string
  default     = "postgres15"
}

variable "vpc_id" {
  description = "(Required when `rds_endpoint` is empty) VPC in which to place the RDS security group. Unused when `rds_endpoint` is supplied."
  type        = string
  default     = ""
}

variable "vpc_subnet_ids" {
  description = "(Required when `rds_endpoint` is empty) Private subnet IDs the RDS subnet group spans. Unused when `rds_endpoint` is supplied."
  type        = list(string)
  default     = []
}

variable "vpc_cidr_block" {
  description = "(Required when `rds_endpoint` is empty) VPC CIDR block — used as the ingress allow-list on the RDS security group so workloads inside the VPC (i.e. SonarQube on EKS) can reach Postgres on port 5432. Unused when `rds_endpoint` is supplied."
  type        = string
  default     = ""
}

# ---------------------------------------------------------------------------
# SonarQube Helm chart configuration.
# ---------------------------------------------------------------------------

variable "sonarqube_namespace" {
  description = "Kubernetes namespace for the SonarQube Helm release."
  type        = string
  default     = "sonarqube"
}

variable "sonarqube_chart_version" {
  description = "SonarQube Helm chart version (chart repo: https://SonarSource.github.io/helm-chart-sonarqube)."
  type        = string
  default     = "10.6.1+2742"
}
