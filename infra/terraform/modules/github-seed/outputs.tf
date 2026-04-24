output "seed_repo_names" {
  value = concat(
    [for r in github_repository.seed : r.full_name],
    [github_repository.juiceshop.full_name]
  )
}

output "sast_seed_repo_names" {
  value = [for r in github_repository.seed : r.full_name]
}

output "juiceshop_repo_full_name" {
  value = github_repository.juiceshop.full_name
}
