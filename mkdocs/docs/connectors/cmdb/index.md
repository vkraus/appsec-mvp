# CMDB connectors

CMDB connectors ingest the authoritative application inventory and team-ownership graph.

!!! note "SCM-first dependency"
    Connectors in this category depend on at least one SCM connector being
    installed first; their findings reference `silver.repositories.repository_id`
    populated by SCM. Walk the [SCM category](../scm/index.md) before installing
    the CMDB connector.

## Capability surface

CMDB sources provide the authoritative application inventory and team-ownership graph. Their data model is relational: an application record references its owning team, associated repositories, and dependent services through foreign-key attributes or a separate relationship table. The specification requires that related CMDB tables be ingested as separate Bronze tables and joined in Silver rather than resolved at ingestion via relationship APIs; this keeps the ingestion entry point stateless and relationship logic testable without API mocks.

Deployments routinely add organization-specific custom attributes (for example, compliance scope or data classification). Schema-on-read at the Bronze layer **SHALL** absorb these custom fields additively without connector changes.

Authentication is typically basic-auth service-account or OAuth 2.0 client-credentials; pagination is offset-based with page sizes in the thousands. Every record exposes an update-timestamp column, which the connector **SHALL** use as the high-water mark for incremental ingestion. CMDB data has no severity dimension.

## Canonical mapping contribution

CMDB sources populate the Silver `application`, `team`, and `ownership` tables. See [Canonical mapping](../../platform/reference/canonical-mapping.md) for the full schema.

## Skills

Three skills cover the connector lifecycle for CMDB sources, with category-specific facts at [Skills](skills.md). The procedural body of each skill is documented at [Connector skills](../../platform/reference/connector-skills.md).

## Connectors in this category

- [ServiceNow](servicenow.md) — reference implementation.
