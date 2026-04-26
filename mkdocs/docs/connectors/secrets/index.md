# Secrets connectors

Secrets connectors ingest credential leak detections from pipelines and repository history.

!!! note "SCM-first dependency"
    Connectors in this category depend on at least one SCM connector being
    installed first. Their findings reference `silver.repositories.repository_id`
    populated by SCM. Walk the [SCM category](../scm/index.md) before installing
    a Secrets connector.

## Capability scope

Secret detection sources differ from other scanner categories in that severity is rarely a first-class output. A single detection carries at most a confidence or verification flag. The specification maps every secret finding to `severity=high` by default. A deployment level override is permitted for detector classes with low entropy.

The dominant deployment style is CLI-based, collected from CI/CD pipeline artifacts. Such tooling has no incremental hook and **SHALL** be treated under the full reload strategy. The natural identification key for a secret finding is the tuple `(repository_id, commit_sha, secret_type, file_path)`. This key is used for deduplication in the documented Silver Finding pattern. Where the source supports live credential verification, the verification outcome populates the documented `validity_status` field in Silver.

Secret detection is almost exclusively CI/CD step in practice. Every commit is a potential leak, so commit level scanning is the operative pattern and the commit SHA is the incremental key. A subset of platforms (GitHub Secret Scanning on the host side) also runs periodic global scans across repository history to catch historical leaks. Connectors should label both outputs with `(repository_id, commit_sha)` so Bronze to Silver deduplication unifies the two sources without double counting.

## Documented mapping contribution

Secret connectors populate the Silver `finding` table with secrets dedup key `(repository_id, commit_sha, secret_type, file_path)`. See [Canonical mapping](../../platform/reference/canonical-mapping.md).

## Skills

Four skills cover the connector lifecycle for Secrets sources, with facts for the category at [Skills](skills.md). The procedural body of each skill is documented at [Connector skills](../../platform/reference/connector-skills.md).

## Connectors in this category

- [TruffleHog](trufflehog.md). Intended integration (no MVP implementation).
