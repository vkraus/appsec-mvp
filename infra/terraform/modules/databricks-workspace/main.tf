resource "databricks_catalog" "mvp" {
  name           = var.catalog_name
  metastore_id   = var.metastore_id
  comment        = "MVP reference implementation — operator procedure"
  isolation_mode = "OPEN"
}

resource "databricks_schema" "bronze" {
  catalog_name = databricks_catalog.mvp.name
  name         = "bronze"
}

resource "databricks_schema" "silver" {
  catalog_name = databricks_catalog.mvp.name
  name         = "silver"
}

resource "databricks_schema" "gold" {
  catalog_name = databricks_catalog.mvp.name
  name         = "gold"
}

resource "databricks_storage_credential" "artifacts" {
  name = "${var.catalog_name}-artifacts"
  aws_iam_role {
    role_arn = var.artifact_bucket_role_arn
  }
  comment = "Access the shared scanner-artifact S3 bucket from Unity Catalog."
}

resource "databricks_external_location" "artifacts" {
  name            = "${var.catalog_name}_artifacts"
  url             = "s3://${var.artifact_bucket}/"
  credential_name = databricks_storage_credential.artifacts.name
  comment         = "Scanner artifact bucket (Semgrep periodic, Semgrep cicd, ZAP cicd)."
}

resource "databricks_volume" "artifacts" {
  catalog_name     = databricks_catalog.mvp.name
  schema_name      = databricks_schema.bronze.name
  name             = "scanner_artifacts"
  volume_type      = "EXTERNAL"
  storage_location = databricks_external_location.artifacts.url
}

resource "databricks_secret_scope" "connectors" {
  name                     = "mvp-connectors"
  initial_manage_principal = "users"
}

resource "databricks_secret" "sonarqube_url" {
  scope        = databricks_secret_scope.connectors.name
  key          = "sonarqube_url"
  string_value = var.sonarqube_url
}

resource "databricks_secret" "sonarqube_token" {
  scope        = databricks_secret_scope.connectors.name
  key          = "sonarqube_token"
  string_value = ""
}

resource "databricks_secret" "zap_url" {
  scope        = databricks_secret_scope.connectors.name
  key          = "zap_url"
  string_value = var.zap_url
}

resource "databricks_secret" "github_org" {
  scope        = databricks_secret_scope.connectors.name
  key          = "github_org"
  string_value = var.github_org
}

resource "databricks_secret" "github_pat" {
  scope        = databricks_secret_scope.connectors.name
  key          = "github_pat"
  string_value = var.github_pat
}

resource "databricks_secret" "servicenow_url" {
  scope        = databricks_secret_scope.connectors.name
  key          = "servicenow_url"
  string_value = var.servicenow_instance_url
}

resource "databricks_secret" "servicenow_username" {
  scope        = databricks_secret_scope.connectors.name
  key          = "servicenow_username"
  string_value = var.servicenow_username
}

resource "databricks_secret" "servicenow_password" {
  scope        = databricks_secret_scope.connectors.name
  key          = "servicenow_password"
  string_value = var.servicenow_password
}

locals {
  connector_jobs = {
    github = {
      entrypoint = "mvp.connectors.github.ingest"
      schedule   = "0 0 */3 * * ?"
    }
    sonarqube = {
      entrypoint = "mvp.connectors.sonarqube.ingest"
      schedule   = "0 15 */3 * * ?"
    }
    semgrep = {
      entrypoint = "mvp.connectors.semgrep.ingest"
      schedule   = "0 30 */3 * * ?"
    }
    owasp_zap = {
      entrypoint = "mvp.connectors.owasp_zap.ingest"
      schedule   = "0 45 */3 * * ?"
    }
  }
}

resource "databricks_job" "connector" {
  for_each = local.connector_jobs
  name     = "mvp-${each.key}"

  task {
    task_key = "ingest"
    python_wheel_task {
      package_name = "mvp"
      entry_point  = each.value.entrypoint
    }
    new_cluster {
      spark_version      = "15.4.x-scala2.12"
      node_type_id       = "i3.xlarge"
      num_workers        = 2
      data_security_mode = "USER_ISOLATION"
    }
    library {
      whl = "dbfs:/Volumes/${databricks_catalog.mvp.name}/${databricks_schema.bronze.name}/wheels/mvp-0.1.0-py3-none-any.whl"
    }
  }

  schedule {
    quartz_cron_expression = each.value.schedule
    timezone_id            = "UTC"
  }
}

resource "databricks_connection" "servicenow" {
  name            = "servicenow"
  connection_type = "SERVICENOW"
  comment         = "ServiceNow CMDB — Lakeflow Connect"
  options = {
    host     = replace(var.servicenow_instance_url, "https://", "")
    username = var.servicenow_username
    password = var.servicenow_password
  }
}

resource "databricks_pipeline" "servicenow" {
  name    = "mvp-servicenow-lakeflow"
  catalog = databricks_catalog.mvp.name
  target  = databricks_schema.bronze.name

  ingestion_definition {
    connection_name = databricks_connection.servicenow.name

    objects {
      table {
        source_schema       = "now"
        source_table        = "cmdb_ci_business_app"
        destination_catalog = databricks_catalog.mvp.name
        destination_schema  = databricks_schema.bronze.name
        destination_table   = "servicenow_business_apps"
      }
    }
    objects {
      table {
        source_schema       = "now"
        source_table        = "cmdb_ci_appl"
        destination_catalog = databricks_catalog.mvp.name
        destination_schema  = databricks_schema.bronze.name
        destination_table   = "servicenow_app_cis"
      }
    }
  }

  serverless = true
  channel    = "CURRENT"
}
