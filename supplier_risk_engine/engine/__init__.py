"""Supplier risk evidence engine (SUPPLIER_RISK_EVIDENCE_ENGINE_PLAN.md).

Pure retrieval over records passed in by the caller: no file access, no LLM,
no MCP, and no Neo4j. Adapters (loader, CLI, MCP server) wrap these
functions and contain no matching logic.
"""

from .lookup import (
    EvidenceIndex,
    build_index,
    compute_snapshot_id,
    describe_database,
    get_evidence,
    lookup_suppliers,
    lookup_suppliers_result,
)
from .models import EngineValidationError, ValidationError
from .reference import ENGINE_VERSION, SCHEMA_VERSION
from .validate import parse_request

__all__ = [
    "ENGINE_VERSION",
    "SCHEMA_VERSION",
    "EngineValidationError",
    "EvidenceIndex",
    "ValidationError",
    "build_index",
    "compute_snapshot_id",
    "describe_database",
    "get_evidence",
    "lookup_suppliers",
    "lookup_suppliers_result",
    "parse_request",
]
