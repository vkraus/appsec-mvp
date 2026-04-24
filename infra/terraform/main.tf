module "aws_foundation" {
  source                   = "./modules/aws-foundation"
  project_prefix           = var.project_prefix
  aws_region               = var.aws_region
  sonarqube_admin_password = var.sonarqube_admin_password
  github_org               = var.github_org
}

module "scanners_eks" {
  source                   = "./modules/scanners-eks"
  depends_on               = [module.aws_foundation]
  eks_cluster_name         = module.aws_foundation.eks_cluster_name
  sonarqube_db_endpoint    = module.aws_foundation.rds_endpoint
  sonarqube_db_name        = module.aws_foundation.rds_db_name
  sonarqube_db_username    = module.aws_foundation.rds_username
  sonarqube_db_password    = module.aws_foundation.rds_password
  sonarqube_admin_password = var.sonarqube_admin_password
  artifact_bucket          = module.aws_foundation.artifact_bucket
  aws_region               = var.aws_region
  semgrep_irsa_role_arn    = module.aws_foundation.semgrep_irsa_role_arn
  semgrep_repo_list        = module.github_seed.seed_repo_names
  github_pat_for_clone     = var.github_pat
}

module "databricks_workspace" {
  source                   = "./modules/databricks-workspace"
  workspace_url            = var.databricks_workspace_url
  metastore_id             = var.databricks_metastore_id
  artifact_bucket          = module.aws_foundation.artifact_bucket
  artifact_bucket_role_arn = module.aws_foundation.databricks_external_location_role_arn
  sonarqube_url            = module.scanners_eks.sonarqube_url
  zap_url                  = module.scanners_eks.zap_url
  github_org               = var.github_org
  github_pat               = var.github_pat
  servicenow_instance_url  = var.servicenow_instance_url
  servicenow_username      = var.servicenow_admin_username
  servicenow_password      = var.servicenow_admin_password
  catalog_name             = var.catalog_name
  depends_on               = [module.scanners_eks]
}

module "github_seed" {
  source                  = "./modules/github-seed"
  github_org              = var.github_org
  aws_oidc_role_arn       = module.aws_foundation.github_actions_role_arn
  ecr_registry_uri        = module.aws_foundation.ecr_registry_uri
  artifact_bucket         = module.aws_foundation.artifact_bucket
  sonarqube_url           = module.scanners_eks.sonarqube_url
  sonarqube_project_token = module.scanners_eks.sonarqube_project_token
  zap_url                 = module.scanners_eks.zap_url
  eks_cluster_name        = module.aws_foundation.eks_cluster_name
  juiceshop_namespace     = module.scanners_eks.juiceshop_namespace
  juiceshop_ingress_host  = module.scanners_eks.juiceshop_ingress_host
  aws_region              = var.aws_region
  depends_on              = [module.scanners_eks]
}

module "servicenow_seed" {
  source          = "./modules/servicenow-seed"
  instance_url    = var.servicenow_instance_url
  admin_username  = var.servicenow_admin_username
  admin_password  = var.servicenow_admin_password
  github_org      = var.github_org
  seed_repo_names = module.github_seed.seed_repo_names
  depends_on      = [module.github_seed]
}
