# End-to-end demo recipe

This directory documents how to wire **multiple** appsec-mvp connectors together for an end-to-end demo. It is **not** part of the framework — the framework lives at `src/`, and each connector's `runtime/` is independently runnable. This recipe ties them together for a thesis-style demo.

## What's here

- `.github/workflows/scan.yml` — a GitHub Actions workflow that, on push to a target repository, runs SonarQube / Semgrep / ZAP scans and uploads results so the corresponding connectors can ingest them.

## Apply order

1. Set up an EKS cluster + RDS Postgres + S3 artifact bucket + ECR registry (operator-supplied; mirrors the spec's "operator brings AWS backbone" stance).
2. Deploy each scanner you want to run by applying its connector's `runtime/`:
   - `cd src/connectors/sonarqube/runtime && terraform apply`
   - `cd src/connectors/semgrep/runtime && terraform apply`
   - `cd src/connectors/owasp_zap/runtime && terraform apply`
3. Deploy the GitHub seed (creates the demo repos + Juice Shop fork):
   - `cd src/connectors/github/runtime && terraform apply`
4. Copy `.github/workflows/scan.yml` into the seeded Juice Shop repository and commit it. Configure the GitHub Actions secrets that the workflow needs (Sonar token, Semgrep S3 path, ZAP URL, etc.).
5. Push a commit to trigger the workflow. Each scanner's connector job will then ingest the produced artifacts.

## Why this lives outside `src/`

The workflow references **multiple** connectors' URLs and tokens by name. It violates the redesign's "no inter-connector dependencies in setup code" rule and therefore cannot live inside any single connector's folder. Keeping it under `examples/` makes the integration boundary explicit.

## Note on connector runtime paths

Per-connector `runtime/` folders referenced above don't exist yet at this point in the redesign — they will be created in a later step (Terraform migration to per-connector runtime/). When those land, this README's apply order will be runnable. Until then, this is the conceptual recipe.
