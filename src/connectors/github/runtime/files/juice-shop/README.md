# juice-shop (appsec-mvp fork)

This folder corresponds to the GitHub fork at [`appsec-mvp/juice-shop`](https://github.com/appsec-mvp/juice-shop). The fork is a copy of OWASP Juice Shop, a deliberately vulnerable Node.js web application widely used for security training and DAST testing.

The framework treats this fork as the demonstrator for the CI/CD scanning pattern. The fork ships with a GitHub Actions workflow that, on every push, builds the Juice Shop image and pushes it to ECR, deploys the image to the EKS cluster, runs Semgrep and SonarQube SAST scans against the source, and runs an OWASP ZAP baseline scan against the deployed application. All scanner outputs feed the same `silver.findings` table via the shared S3 artifact bucket. The `trigger_context` column distinguishes CI/CD runs from scheduled scans.

This folder also contains two appsec-mvp overlays that Terraform commits into the fork:

- `.sonarcloud.properties` provides the SonarQube scan configuration.
- `deploy/juiceshop.yaml` is the Kubernetes manifest applied by the CI workflow during the deploy step.

Source code for Juice Shop itself lives in the fork, not in this folder. To upgrade Juice Shop, update the fork.
