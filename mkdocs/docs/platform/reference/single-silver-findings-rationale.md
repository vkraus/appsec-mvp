# Why a single `silver.findings` table

The physical Silver schema stores all finding categories (SAST, SCA, secret, DAST, container, IaC) in a single table `silver.findings`, discriminated by a `category` column, rather than splitting into tables specific to each category such as `silver.sast_findings`, `silver.sca_findings`, and so on. This page captures the reasoning.

## Cross category analytics

The standard Silver Finding mapping is already a union over sources. Every standard field has a single definition, and each source populates the subset of fields its category produces. A physical split would instantiate that union as N separate tables with identical base columns and different columns for each category. Cross category queries such as "all open findings on a repository" or "top five risky applications by finding volume across all categories" would then require `UNION ALL` across N tables, and every new category would add another operand.

## Dedup routing

Dedup logic for each category treats `category` as a routing key. Collocating records in one table lets a single transform apply the dedup tuple conditional on category without maintaining N parallel transform modules.

## Requirement traceability

The requirement catalog is category shaped. REQ-DEDUP applies to SAST, SCA, and secret with different tuples. Binding those requirements to one physical table keeps the traceability matrix readable.

## Sparse nulls are cheap

Sparse nullable columns are the accepted cost of the union schema. At the volumes the platform handles (hundreds of millions of findings in the largest expected deployments), columnar compression in Delta Lake makes NULLs cheap to store and skip.
