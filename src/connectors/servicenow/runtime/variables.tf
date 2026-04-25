# ---------------------------------------------------------------------------
# ServiceNow tenant — operator-supplied connection details. These are the
# only inputs strictly required to seed the demo CMDB business-app records.
# ---------------------------------------------------------------------------

variable "instance_url" {
  description = "ServiceNow instance URL, e.g. `https://devXXXXX.service-now.com`. Must include the scheme; trailing slashes are not required (the module composes `$${instance_url}/api/now/...` paths verbatim)."
  type        = string
}

variable "admin_username" {
  description = "ServiceNow service-account username with write access to the `cmdb_ci_business_app`, `cmdb_ci_appl`, and `cmdb_rel_ci` tables. Used together with `admin_password` for HTTP Basic auth on the REST API calls."
  type        = string
}

variable "admin_password" {
  description = "ServiceNow service-account password (sensitive)."
  type        = string
  sensitive   = true
}

# ---------------------------------------------------------------------------
# Demo seed data. The defaults match the github runtime's seeded repos
# *by coincidence* — there is no Terraform-level reference between the two
# runtimes, per the redesign's no-inter-connector-dependency rule. If you
# change one, change the other, or the cross-source `silver.app_repo` join
# in analytics will not resolve.
# ---------------------------------------------------------------------------

variable "github_org" {
  description = "GitHub org that owns the seeded repos. The source module declared this variable but did not consume it in the CMDB record bodies; it is preserved here for forward-compatibility (operators wiring richer CMDB metadata may want it)."
  type        = string
  default     = "appsec-mvp-demo"
}

variable "seed_repo_names" {
  description = "List of repo names to seed as CMDB application records. Default matches the github runtime's seeded repos *by coincidence* — there is no Terraform import between the two runtimes. The first two repos become children of the `AppSec Demo Frontend` business app; the third (if present) becomes a child of `AppSec Demo Backend`."
  type        = list(string)
  default     = ["seed-python-a", "seed-javascript-b", "juiceshop"]
}

variable "project_prefix" {
  description = "Short slug retained for parity with the other connector runtimes. The ServiceNow runtime does not currently use it — CMDB record names are hardcoded (`AppSec Demo Frontend`, `AppSec Demo Backend`) — but operators forking this module to namespace their seeded records will want it."
  type        = string
  default     = "appsec-mvp"
}
