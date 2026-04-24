variable "project_prefix" { type = string }
variable "aws_region" { type = string }
variable "sonarqube_admin_password" {
  type      = string
  sensitive = true
}
variable "github_org" { type = string }

variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}
variable "eks_version" {
  type    = string
  default = "1.30"
}
variable "eks_node_instance_type" {
  type    = string
  default = "t3.large"
}
variable "eks_node_desired_size" {
  type    = number
  default = 3
}
