output "business_app_sysids" {
  description = "Map of seeded business-app names (`AppSec Demo Frontend`, `AppSec Demo Backend`) to their ServiceNow `sys_id` values, as returned by the table-API lookup that runs after the POST. Useful for wiring downstream automation that needs to reference the seeded records."
  value       = local.app_sysids
}
