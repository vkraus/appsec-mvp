# BenchmarkJava (appsec-mvp fork)

This folder corresponds to the GitHub fork at [`appsec-mvp/BenchmarkJava`](https://github.com/appsec-mvp/BenchmarkJava). The fork is a copy of the OWASP Benchmark project for Java. OWASP Benchmark is a deliberately vulnerable Java web application that exercises a wide range of CWE categories. The framework uses it as a SAST target.

The framework runs Semgrep and SonarQube against this fork as part of the scheduled scanning pattern that walks the whole organization. Both scanners produce findings on the same Benchmark test cases. The framework normalizes the output into the `silver.findings` table, and the `tool` column distinguishes the source.

This folder is intentionally empty of source code. The Terraform module references the fork via a `data "github_repository"` block. The framework pushes nothing from this repository into the fork. To upgrade the upstream Benchmark version, update the fork itself.
