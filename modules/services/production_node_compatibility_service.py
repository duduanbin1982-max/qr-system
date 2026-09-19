"""Dual-read compatibility service for the staged production-node cutover."""

from modules import config
from modules.repositories.context import resolve_db
from modules.repositories.production_node_repository import ProductionNodeRepository


COMPARE_FIELDS = (
    "process_id",
    "status",
    "calendar_id",
    "capacity_mode",
    "capacity_minutes",
    "scheduled_operations",
    "occupied_minutes",
    "occupancy_digest",
    "downtime_count",
    "downtime_digest",
    "conflict_count",
)


def _number(value):
    return float(value or 0)


def _integer(value):
    return int(value or 0)


def _mapping_sort_key(value):
    return (0, value) if isinstance(value, int) else (1, str(value))


def normalize_legacy_resources(resources):
    return sorted(
        [
            {
                "stable_mapping_id": _integer(row.get("id")),
                "process_id": _integer(row.get("process_id")),
                "status": str(row.get("status") or ""),
                "calendar_id": _integer(row.get("calendar_id")),
                "capacity_mode": "exclusive",
                "capacity_minutes": _number(row.get("daily_minutes")),
                "scheduled_operations": _integer(row.get("scheduled_operations")),
                "occupied_minutes": _number(row.get("occupied_minutes")),
                "occupancy_digest": str(row.get("occupancy_digest") or ""),
                "downtime_count": _integer(row.get("downtime_count")),
                "downtime_digest": str(row.get("downtime_digest") or ""),
                "conflict_count": _integer(row.get("conflict_count")),
            }
            for row in resources
        ],
        key=lambda row: row["stable_mapping_id"],
    )


def normalize_node_resources(resources):
    return sorted(
        [
            {
                "stable_mapping_id": (
                    _integer(row.get("legacy_process_line_id"))
                    if row.get("legacy_process_line_id") is not None
                    else f"unmapped-node:{_integer(row.get('id'))}"
                ),
                "process_id": _integer(row.get("process_id")),
                "status": str(row.get("status") or ""),
                "calendar_id": _integer(row.get("calendar_id")),
                "capacity_mode": str(row.get("capacity_mode") or ""),
                "capacity_minutes": _number(row.get("capacity_minutes")),
                "scheduled_operations": _integer(row.get("scheduled_operations")),
                "occupied_minutes": _number(row.get("occupied_minutes")),
                "occupancy_digest": str(row.get("occupancy_digest") or ""),
                "downtime_count": _integer(row.get("downtime_count")),
                "downtime_digest": str(row.get("downtime_digest") or ""),
                "conflict_count": _integer(row.get("conflict_count")),
            }
            for row in resources
        ],
        key=lambda row: _mapping_sort_key(row["stable_mapping_id"]),
    )


def compatibility_difference(legacy_payload, node_payload):
    legacy_by_id = {row["stable_mapping_id"]: row for row in legacy_payload}
    node_by_id = {row["stable_mapping_id"]: row for row in node_payload}
    changes = []
    for mapping_id in sorted(
        set(legacy_by_id) & set(node_by_id), key=_mapping_sort_key
    ):
        legacy = legacy_by_id[mapping_id]
        node = node_by_id[mapping_id]
        for field in COMPARE_FIELDS:
            if legacy.get(field) != node.get(field):
                changes.append(
                    {
                        "stable_mapping_id": mapping_id,
                        "field": field,
                        "legacy": legacy.get(field),
                        "node": node.get(field),
                    }
                )
    return {
        "missing_from_nodes": sorted(
            set(legacy_by_id) - set(node_by_id), key=_mapping_sort_key
        ),
        "missing_from_legacy": sorted(
            set(node_by_id) - set(legacy_by_id), key=_mapping_sort_key
        ),
        "changes": changes,
        "coverage": {
            "legacy_count": len(legacy_payload),
            "node_count": len(node_payload),
            "truncated": False,
        },
    }


class ProductionNodeCompatibilityService:
    @staticmethod
    def list_resources(process_id=None, limit=500, db=None):
        connection = resolve_db(db)
        audit_enabled = bool(config.PRODUCTION_NODE_COMPAT_AUDIT_ENABLED)
        owns_transaction = False
        if audit_enabled and not connection.in_transaction:
            # Compatibility evidence must describe the same SQLite snapshot as
            # both reads.  In WAL mode a deferred BEGIN may let another writer
            # commit after the first read and then fail when this transaction
            # upgrades to insert its observation (SQLITE_BUSY_SNAPSHOT).
            # BEGIN IMMEDIATE reserves the single writer slot before either
            # read.  The connection busy_timeout keeps lock acquisition
            # bounded, and this transaction contains only the two reads plus
            # one idempotent observation insert.
            connection.execute("BEGIN IMMEDIATE")
            owns_transaction = db is None
        try:
            if audit_enabled:
                legacy = ProductionNodeRepository.list_legacy_resources(
                    process_id=process_id, db=connection, full=True
                )
                nodes = ProductionNodeRepository.list_nodes(
                    process_id=process_id, db=connection, full=True
                )
                normalized_legacy = normalize_legacy_resources(legacy)
                normalized_nodes = normalize_node_resources(nodes)
                ProductionNodeRepository.record_compatibility_observation(
                    scope="resource_list",
                    source_id=(
                        int(process_id) if process_id not in (None, "") else None
                    ),
                    legacy_payload=normalized_legacy,
                    node_payload=normalized_nodes,
                    difference=compatibility_difference(
                        normalized_legacy, normalized_nodes
                    ),
                    db=connection,
                )
                bounded_limit = ProductionNodeRepository._bounded_limit(limit)
                result = (
                    nodes[:bounded_limit]
                    if config.PRODUCTION_NODE_QUERY_ENABLED
                    else legacy[:bounded_limit]
                )
            elif config.PRODUCTION_NODE_QUERY_ENABLED:
                result = ProductionNodeRepository.list_nodes(
                    process_id=process_id, limit=limit, db=connection
                )
            else:
                result = ProductionNodeRepository.list_legacy_resources(
                    process_id=process_id, limit=limit, db=connection
                )
            if owns_transaction:
                connection.commit()
            return result
        except Exception:
            if owns_transaction:
                connection.rollback()
            raise
