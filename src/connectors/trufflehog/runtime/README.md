# TruffleHog connector — source-system runtime

This Terraform module provisions the **Unity Catalog Volume** that the TruffleHog connector reads from. TruffleHog itself is a CLI scanner that runs on CI/CD runners (or on the operator's existing host-side scan infrastructure) and emits line-delimited JSON. The operator's CI uploads those artefacts to a cloud bucket (S3 / ADLS / GCS); this module creates the UC Volume that maps onto that bucket so autoloader can ingest the JSON into `bronze_trufflehog.findings`.

It is the documented CLI-artefact pattern (CLAUDE.md §"Ingestion tooling preference order") — TruffleHog has no live API to call, so a Volume-backed artefact drop is the native fit.

## Prerequisites

- A cloud storage bucket (S3, ADLS, GCS) where CI runs drop TruffleHog `--json` output. **Pre-provisioned by the operator** — this module does not create cloud buckets.
- AWS credentials (or equivalent for ADLS / GCS) with read access to the bucket. Loaded into a Databricks secret scope via `scripts/load-secrets.sh` so Databricks Connect / autoloader can authenticate to the bucket.
- The `bronze_trufflehog` schema in Unity Catalog. Declared by the connector's Databricks Asset Bundle (`src/connectors/trufflehog/resources/schemas.yml`) and applied alongside the rest of the bundle — apply that before this runtime, or in the same bundle deploy.

## What it creates

- A `databricks_volume` named `artefacts` of type `EXTERNAL` under `<catalog>.bronze_trufflehog`, with `storage_location = var.trufflehog_artifact_volume_path`. That is the only resource — no IAM, no Kubernetes, no compute.

## Setup

1. Export the credentials for the artefact bucket reader:

   ```bash
   export AWS_ACCESS_KEY_ID=...
   export AWS_SECRET_ACCESS_KEY=...
   ```

2. Load them into the Databricks secret scope (idempotent — re-runs replace the value):

   ```bash
   bash src/connectors/trufflehog/scripts/load-secrets.sh
   ```

   The script writes a single JSON blob `{access_key_id, secret_access_key}` to scope `mvp-connectors`, key `trufflehog_aws_credentials`. Override scope/key via the `TRUFFLEHOG_ARTIFACT_VOLUME_SECRET_SCOPE` / `TRUFFLEHOG_ARTIFACT_VOLUME_SECRET_KEY` env vars.

3. Apply the runtime:

   ```bash
   cd src/connectors/trufflehog/runtime
   terraform init
   terraform apply \
     -var "catalog=appsec_dev" \
     -var "trufflehog_artifact_volume_path=/Volumes/appsec_dev/bronze_trufflehog/artefacts"
   ```

4. Apply the connector's bundle (`databricks bundle deploy --target dev`) — this creates the bronze schema (if not already present) and the ingestion job that reads from the Volume.

## CI integration

The operator's CI configures TruffleHog to dump JSON to the artefact bucket. Example (S3):

```bash
trufflehog git --json https://github.com/<org>/<repo> > out.json
aws s3 cp out.json s3://<bucket>/trufflehog/<repo>/$(date -u +%FT%TZ).json
```

The expected output shape is one TruffleHog finding per line. See `runtime/files/sample.json` for a sanitised reference record (the `Raw` field is intentionally redacted — TruffleHog's redaction rule is enforced at Bronze→Silver and the literal value never enters the connector's pipeline).

## Operator-supplied inputs

### Required

| Variable | Description |
|---|---|
| `catalog` | Unity Catalog name. The Volume is created in `<catalog>.bronze_trufflehog.artefacts`. |
| `trufflehog_artifact_volume_path` | UC Volume path — the filesystem-style location autoloader reads from, e.g. `/Volumes/appsec_dev/bronze_trufflehog/artefacts`. The underlying cloud bucket must be pre-provisioned. |

### Optional

| Variable | Description | Default |
|---|---|---|
| `trufflehog_artifact_volume_secret_scope` | Databricks secret scope holding the artefact-bucket reader credentials. | `mvp-connectors` |
| `trufflehog_artifact_volume_secret_key` | Secret key under that scope. The script loads a JSON blob `{access_key_id, secret_access_key}`. | `trufflehog_aws_credentials` |

## Outputs

`bronze_schema_full_name`, `volume_path`, `volume_full_name` — useful as inputs to downstream wiring (Lakeflow autoloader pipelines, `GRANT` statements, the Bronze→Silver job).

## Teardown

```bash
cd src/connectors/trufflehog/runtime
terraform destroy
```

This removes the UC Volume only. The underlying cloud bucket and any artefacts already uploaded to it are **not** managed by this module — delete them out-of-band if no longer needed.

## Validation evidence

stub.

## Independence

This module references only operator-supplied inputs and the Databricks provider. It does not depend on any other connector's runtime, per the redesign's no-inter-connector-dependency rule. The bronze schema it references is declared by this connector's own bundle (`resources/schemas.yml`), not by another connector's runtime.

This module is intended to be used as a **root** module. It declares its own `databricks` provider via `versions.tf`; using it via `module "..."` from a parent module will collide with the parent's providers.
