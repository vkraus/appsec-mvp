"""Connector contract types per thesis section 2.4.1.

The framework prescribes a pair of entry points per connector:

    def ingest(run_id: str, state: ConnectorState) -> BatchDescriptor
    def transform(bronze_df) -> silver_df

These TypedDicts establish the shape. The wrappers in each connector
dispatch to the underlying ingestion primitive (Lakeflow Connect pipeline,
SDK fetchers, artifact-path reader) without changing that primitive's
signature.

Real state persistence, meaning reading and writing HWM values to a Unity
Catalog control table, is queued as Future Work (see thesis section 4 on
future work). The current wrappers accept ``state`` as a plain dict.
Callers pass ``{}`` for first-run semantics.
"""
from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class ConnectorState(TypedDict):
    """Input state for one ingestion run.

    Keys:
        source: stable identifier of the source system (e.g. ``"github"``).
        run_id: idempotency and observability key.
        hwm_value: opaque high-water-mark marker (timestamp, cursor, or
            commit SHA). Shape is connector-specific.
        extra: connector-specific configuration that is not part of the
            framework contract (e.g. GitHub org name, ZAP API URL).
    """

    source: str
    run_id: str
    hwm_value: NotRequired[str | None]
    extra: NotRequired[dict[str, Any]]


class BatchDescriptor(TypedDict):
    """Output descriptor from one ingestion run."""

    run_id: str
    source: str
    record_count: int
    new_hwm_value: NotRequired[str | None]
    bronze_table: str
