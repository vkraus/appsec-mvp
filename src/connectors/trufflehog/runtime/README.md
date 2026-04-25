# TruffleHog connector, runtime for the source system

This Terraform module provisions the **Unity Catalog Volume** that the TruffleHog connector reads from. TruffleHog itself is a CLI scanner that runs on CI/CD runners (or on the existing host scan infrastructure of the user) and emits JSON with one record per line. The CI of the user uploads those artefacts to a cloud bucket (S3, ADLS, or GCS). This module creates the UC Volume that maps onto that bucket so autoloader can ingest the JSON into `bronze_trufflehog.findings`.

It is the documented pattern for CLI artefacts (CLAUDE.md §"Ingestion tooling preference order"). TruffleHog has no live API to call, so a drop of artefacts backed by a Volume is the native fit.

## Prerequisites

- A cloud storage bucket (S3, ADLS, or GCS) where CI runs drop TruffleHog `--json` output. **Provisioned by the user in advance**. This module does not create cloud buckets.
- AWS credentials (or equivalent for ADLS or GCS) with read access to the bucket. Loaded into a Databricks secret scope via `scripts/load-secrets.sh` so Databricks Connect or autoloader can authenticate to the bucket.
- The `bronze_trufflehog` schema in Unity Catalog. Declared by the Databricks Asset Bundle for this connector (`src/connectors/trufflehog/resources/schemas.yml`) and applied alongside the rest of the bundle. Apply that before this runtime, or in the same bundle deploy.

## What it creates

- A `databricks_volume` named `artefacts` of type `EXTERNAL` under `<catalog>.bronze_trufflehog`, with `storage_location = var.trufflehog_artifact_volume_path`. That is the only resource. No IAM, no Kubernetes, no compute.

## Setup

1. Export the credentials for the artefact bucket reader:

   ```bash
   export AWS_ACCESS_KEY_ID=...
   export AWS_SECRET_ACCESS_KEY=...
   ```

2. Load them into the Databricks secret scope (idempotent, since re-runs replace the value):

   ```bash
   bash src/connectors/trufflehog/scripts/load-secrets.sh
   ```

   The script writes a single JSON blob `{access_key_id, secret_access_key}` to scope `mvp-connectors`, key `trufflehog_aws_credentials`. Override scope or key via the `TRUFFLEHOG_ARTIFACT_VOLUME_SECRET_SCOPE` and `TRUFFLEHOG_ARTIFACT_VOLUME_SECRET_KEY` env vars.

3. Apply the runtime:

   ```bash
   cd src/connectors/trufflehog/runtime
   terraform init
   terraform apply \
     -var "catalog=appsec_dev" \
     -var "trufflehog_artifact_volume_path=/Volumes/appsec_dev/bronze_trufflehog/artefacts"
   ```

4. Apply the bundle for this connector (`databricks bundle deploy --target dev`). This creates the bronze schema (if not already present) and the ingestion job that reads from the Volume.

## CI integration

The CI of the user configures TruffleHog to dump JSON to the artefact bucket. Example (S3):

```bash
trufflehog git --json https://github.com/<org>/<repo> > out.json
aws s3 cp out.json s3://<bucket>/trufflehog/<repo>/$(date -u +%FT%TZ).json
```

The expected output structure is one TruffleHog finding per line. See `runtime/files/sample.json` for a sanitised reference record. The `Raw` field is intentionally redacted. The TruffleHog redaction rule is enforced at Bronze to Silver and the literal value never enters the pipeline of this connector.

## Inputs supplied by the user

### Required

| Variable | Description |
|---|---|
| `catalog` | Unity Catalog name. The Volume is created in `<catalog>.bronze_trufflehog.artefacts`. |
| `trufflehog_artifact_volume_path` | UC Volume path. The location in filesystem style that autoloader reads from, e.g. `/Volumes/appsec_dev/bronze_trufflehog/artefacts`. The underlying cloud bucket must be provisioned in advance. |

### Optional

| Variable | Description | Default |
|---|---|---|
| `trufflehog_artifact_volume_secret_scope` | Databricks secret scope holding the credentials of the reader for the artefact bucket. | `mvp-connectors` |
| `trufflehog_artifact_volume_secret_key` | Secret key under that scope. The script loads a JSON blob `{access_key_id, secret_access_key}`. | `trufflehog_aws_credentials` |

## Outputs

`bronze_schema_full_name`, `volume_path`, and `volume_full_name`. Useful as inputs to downstream wiring (Lakeflow autoloader pipelines, `GRANT` statements, the Bronze to Silver job).

## Teardown

```bash
cd src/connectors/trufflehog/runtime
terraform destroy
```

This removes the UC Volume only. The underlying cloud bucket and any artefacts already uploaded to it are **not** managed by this module. Delete them out of band if no longer needed.

## Validation evidence

stub.

## Independence

This module references only inputs supplied by the user and the Databricks provider. It does not depend on the runtime of any other connector. This follows the rule from the redesign that connector runtimes must not depend on each other. The bronze schema it references is declared by the bundle of this connector (`resources/schemas.yml`), not by the runtime of another connector.

This module is intended to be used as a **root** module. It declares its own `databricks` provider via `versions.tf`. Using it via `module "..."` from a parent module will collide with the providers of the parent.
