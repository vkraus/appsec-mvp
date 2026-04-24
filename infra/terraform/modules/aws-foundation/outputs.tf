output "vpc_id" { value = module.vpc.vpc_id }
output "private_subnet_ids" { value = module.vpc.private_subnets }
output "eks_cluster_name" { value = module.eks.cluster_name }
output "eks_cluster_endpoint" { value = module.eks.cluster_endpoint }
output "eks_cluster_ca" { value = module.eks.cluster_certificate_authority_data }

output "rds_endpoint" { value = module.rds_sonarqube.db_instance_endpoint }
output "rds_db_name" { value = module.rds_sonarqube.db_instance_name }
output "rds_username" { value = module.rds_sonarqube.db_instance_username }
output "rds_password" {
  value     = random_password.sonarqube_db.result
  sensitive = true
}
output "artifact_bucket" { value = aws_s3_bucket.artifacts.id }
output "ecr_registry_uri" { value = aws_ecr_repository.juiceshop.repository_url }

output "github_actions_role_arn" { value = aws_iam_role.github_actions.arn }
output "databricks_external_location_role_arn" { value = aws_iam_role.databricks_external_location.arn }

output "semgrep_irsa_role_arn" { value = module.semgrep_irsa.iam_role_arn }
