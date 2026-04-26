# SCM connectors

SCM connectors ingest repositories, pull requests, and branch policies used to attribute findings to teams.

## Capability contract

SCM sources populate the repositories, commits, pull requests, and branch policy tables that the framework uses to attribute findings to teams. They expose REST and in some cases GraphQL APIs, with moderate data volumes and frequent updates. Authentication uses personal access tokens (PATs) or OAuth. Pagination is predominantly cursor based, with keyset pagination on some platforms.

Every SCM connector **SHALL** select its incremental strategy from a three option preference order:

1. **Webhook or event stream delivery** where the source exposes one. The connector subscribes and materializes events into Bronze in near real time.
2. **Source native `updated_at` (or equivalent) timestamp** as the high water mark, advanced per run and persisted to the state table.
3. **Full reload**, reserved for sources exposing neither a webhook nor a reliable update timestamp (rare in practice).

The decision for each source is recorded in the connector pages. `config.yml` declares which mode applies.

## Standard mapping contribution

SCM sources populate the Silver `repository`, `pull_request`, and `branch_policy` tables. See [Standard mapping](../../platform/reference/canonical-mapping.md).

## Skills

Four skills cover the connector lifecycle for SCM sources, with category specific facts at [Skills](skills.md). The procedural body of each skill is documented at [Connector skills](../../platform/reference/connector-skills.md).

## Connectors in this category

- [GitHub](github.md): reference implementation.
- [GitLab](gitlab.md): intended integration (no MVP implementation).
