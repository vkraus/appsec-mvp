"""Dependency-Track connector module (SCA, server/periodic-global).

Polls the Dependency-Track REST API for projects, components, and findings;
flattens per-component vulnerability records to silver.findings with the
SCA dedup key (repository_id, package_name, cve_id).
"""
