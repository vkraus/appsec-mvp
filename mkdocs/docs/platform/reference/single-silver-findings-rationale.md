# Why a single `silver.findings` table

The physical Silver schema stores all finding categories (SAST, SCA, secret, DAST, WAF, container, IaC) in a single table `silver.findings`, discriminated by a `category` column, rather than splitting into tables specific to each category such as `silver.sast_findings`, `silver.sca_findings`, and so on. This page captures the reasoning.

## Cross category analytics

The standard Silver Finding mapping is already a union over sources. Every standard field has a single definition, and each source populates the subset of fields its category produces. A physical split would instantiate that union as N separate tables with identical base columns and different columns for each category. Cross category queries such as "all open findings on a repository" or "top five risky applications by finding volume across all categories" would then require `UNION ALL` across N tables, and every new category would add another operand.

## Dedup routing

Dedup logic for each category treats `category` as a routing key. Collocating records in one table lets a single transform apply the dedup tuple conditional on category without maintaining N parallel transform modules.

## Requirement traceability

The requirement catalog is category shaped. REQ-DEDUP applies to SAST, SCA, and secret with different tuples. Binding those requirements to one physical table keeps the traceability matrix readable.

## Sparse nulls are cheap

Sparse nullable columns are the accepted cost of the union schema. At the volumes the platform handles (hundreds of millions of findings in the largest expected deployments), columnar compression in Delta Lake makes NULLs cheap to store and skip.

## WAF joins the canonical table

WAF events are append-only edge-event observations rather than triaged vulnerabilities, and earlier iterations of the design carved them out into a dedicated `silver.waf_events` table. That carve-out has been collapsed. WAF now projects each event as one finding row on `silver.findings`, the same canonical target as SAST, SCA, secret, and DAST: severity is derived from the action via an action-keyed lookup, status is the literal `open` and never transitions (matching the trufflehog convention for sources with no native lifecycle), and `finding_id` is a deterministic SHA-256 hash so re-delivered events collapse at the Bronze-to-Silver MERGE.

The argument for one canonical table strengthens with WAF in the union: cross-category queries such as "all open findings on a given application" or "top risky applications by finding volume across detection tiers" now span runtime telemetry as well as static and dynamic testing, without `UNION ALL` between a finding table and an event table. WAF telemetry beyond the canonical projection (`source_ip`, `country`, `http_method`, `response_code`, `sampling_weight`, `rule_type`, and the `action` value itself) is intentionally dropped from `silver.findings`; operators query the upstream WAF logs (S3 / CloudWatch) for that detail.
