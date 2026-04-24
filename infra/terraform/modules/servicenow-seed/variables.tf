variable "instance_url" {
  type = string
}

variable "admin_username" {
  type = string
}

variable "admin_password" {
  type      = string
  sensitive = true
}

variable "github_org" {
  type = string
}

variable "seed_repo_names" {
  type = list(string)
}
