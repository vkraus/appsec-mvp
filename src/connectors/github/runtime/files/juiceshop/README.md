# Juice Shop — MVP seed + CI/CD demonstration

This repository is a pinned copy of [OWASP Juice Shop](https://github.com/juice-shop/juice-shop)
at tag `v17.2.0` plus a CI/CD pipeline that builds, scans, and deploys it to
the thesis-MVP EKS cluster on every push.

## Why this exists

The thesis MVP exercises two Semgrep operational patterns: **periodic-global**
(an EKS CronJob scanning all registered repos) and **CI/CD-step** (scans run
inside a pipeline on each push). This repo is the CI/CD-step demonstrator.
The pipeline additionally runs a SonarQube scan and an OWASP ZAP baseline
scan against the freshly-deployed app. All scanner outputs feed the same
`silver.findings` table via the shared S3 artifact bucket, distinguished by
a `trigger_context` field.

## Maintenance

When upgrading to a new Juice Shop release: bump the tag in this README, run
`terraform apply` (which re-seeds this repo), and verify the workflow still
green.
