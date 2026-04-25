# ---------------------------------------------------------------------------
# Provider configuration. The ServiceNow runtime is the most isolated of the
# connector runtimes — no AWS, no Kubernetes, no IAM. It speaks plain HTTP
# Basic auth to the ServiceNow REST API:
#
#   - `data "http"` reads sys_ids of seeded business-app records.
#   - `terraform_data` + `local-exec curl` issues the POST calls (matches the
#     source module's approach; ServiceNow's table API does not have a
#     first-class Terraform provider, so curl-via-local-exec is the native
#     pattern for seeding demo CMDB records).
#
# Migrated faithfully from infra/terraform/modules/servicenow-seed/main.tf.
# ---------------------------------------------------------------------------

locals {
  business_apps = {
    "AppSec Demo Frontend" = {
      criticality = "2 - high"
      repos       = slice(var.seed_repo_names, 0, 2)
    }
    "AppSec Demo Backend" = {
      criticality = "1 - critical"
      repos       = length(var.seed_repo_names) > 2 ? [var.seed_repo_names[2]] : []
    }
  }

  auth_header = "Basic ${base64encode("${var.admin_username}:${var.admin_password}")}"
}

resource "terraform_data" "business_app" {
  for_each = local.business_apps

  triggers_replace = {
    name        = each.key
    criticality = each.value.criticality
  }

  provisioner "local-exec" {
    interpreter = ["bash", "-lc"]
    command     = <<EOT
curl -sS -X POST "${var.instance_url}/api/now/table/cmdb_ci_business_app" \
  -u "${var.admin_username}:${var.admin_password}" \
  -H "Content-Type: application/json" -H "Accept: application/json" \
  -d '{"name":"${each.key}","operational_status":"1","business_criticality":"${each.value.criticality}"}'
EOT
  }
}

data "http" "business_app_sysid" {
  for_each = local.business_apps

  url = "${var.instance_url}/api/now/table/cmdb_ci_business_app?sysparm_query=name=${urlencode(each.key)}&sysparm_fields=sys_id&sysparm_limit=1"
  request_headers = {
    Authorization = local.auth_header
    Accept        = "application/json"
  }
  depends_on = [terraform_data.business_app]
}

locals {
  app_sysids = {
    for name, resp in data.http.business_app_sysid :
    name => jsondecode(resp.response_body).result[0].sys_id
  }
}

resource "terraform_data" "app_ci" {
  for_each = merge([
    for app_name, cfg in local.business_apps : {
      for repo in cfg.repos :
      "${app_name}::${repo}" => {
        app_name  = app_name
        repo_full = repo
        app_sysid = local.app_sysids[app_name]
      }
    }
  ]...)

  triggers_replace = {
    repo = each.value.repo_full
    app  = each.value.app_name
  }

  provisioner "local-exec" {
    interpreter = ["bash", "-lc"]
    command     = <<EOT
APPL_SYSID=$(curl -sS -X POST "${var.instance_url}/api/now/table/cmdb_ci_appl" \
  -u "${var.admin_username}:${var.admin_password}" \
  -H "Content-Type: application/json" -H "Accept: application/json" \
  -d '{"name":"${each.value.repo_full}","short_description":"GitHub repository ${each.value.repo_full}"}' \
  | jq -r '.result.sys_id')

curl -sS -X POST "${var.instance_url}/api/now/table/cmdb_rel_ci" \
  -u "${var.admin_username}:${var.admin_password}" \
  -H "Content-Type: application/json" -H "Accept: application/json" \
  -d "{\"parent\":\"${each.value.app_sysid}\",\"child\":\"$APPL_SYSID\",\"type\":\"Depends on::Used by\"}"
EOT
  }
}
