"""Legacy process/route read projections over versioned master data."""

from collections import Counter
import json
import logging

from modules import config
from modules.domain.process_versioning import assert_legacy_master_data_write_allowed
from modules.repositories.process_version_repository import ProcessVersionRepository
from modules.repositories.route_repository import RouteRepository
from modules.repositories.route_version_repository import RouteVersionRepository


logger = logging.getLogger("qr-system.compatibility")


class LegacyProcessCompatibilityService:
    PROCESS_COMPARE_FIELDS = (
        "process_name",
        "description",
        "category",
        "seq_order",
        "status",
        "created_at",
    )
    ROUTE_COMPARE_FIELDS = (
        "name",
        "description",
        "category",
        "status",
        "created_at",
        "used_orders",
        "used_products",
        "is_locked",
    )
    ROUTE_ITEM_COMPARE_FIELDS = (
        "process_id",
        "seq_order",
        "required_audit",
        "process_name",
        "category",
        "process_status",
    )

    @staticmethod
    def require_legacy_write():
        return assert_legacy_master_data_write_allowed(
            not config.PROCESS_LEGACY_WRITE_BLOCKED
        )

    @staticmethod
    def _truthy(value):
        return str(value or "").strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _sort_value(value):
        if value is None:
            return (1, "")
        if isinstance(value, (int, float)):
            return (0, value)
        return (0, str(value).casefold())

    @staticmethod
    def _process_projection(root):
        version = root.get("current_version") or {}
        return {
            "id": root["id"],
            "process_name": version.get("name", root.get("name", "")),
            "description": version.get("description", root.get("description", "")),
            "category": version.get("category", root.get("category", "")),
            "seq_order": version.get("seq_order", root.get("seq_order", 0)),
            "status": root.get("status", "inactive"),
            "created_at": root.get("created_at", ""),
            "process_code": root.get("process_code", ""),
            "lifecycle_status": root.get("lifecycle_status", "active"),
            "current_effective_version_id": root.get("current_effective_version_id"),
            "process_version_id": version.get("id"),
            "process_version": version.get("version"),
            "version_status": version.get("status"),
            "effective_from": version.get("effective_from", ""),
            "effective_to": version.get("effective_to", ""),
            "revision_reason": version.get("revision_reason", ""),
            "version_row_version": version.get("row_version"),
        }

    @staticmethod
    def _route_items(route_id, version, legacy_route):
        if not version:
            return [dict(item) for item in (legacy_route or {}).get("processes", [])]
        items = []
        for item in version.get("items") or []:
            version_status = item.get("process_version_status")
            items.append(
                {
                    "id": item.get("id"),
                    "route_id": route_id,
                    "process_id": item["process_id"],
                    "process_version_id": item["process_version_id"],
                    "process_version": item.get("process_version"),
                    "seq_order": item["seq_order"],
                    "is_required": item.get("is_required", 1),
                    "required_audit": item.get("required_audit", 0),
                    "process_name": item.get("process_name_snapshot", ""),
                    "category": item.get("process_category", ""),
                    "process_status": (
                        "active" if version_status == "published" else "inactive"
                    ),
                    "process_version_status": version_status,
                }
            )
        return items

    @staticmethod
    def _route_projection(root, legacy_route, usage):
        version = root.get("current_version") or {}
        open_version = root.get("open_version") or {}
        route = {
            "id": root["id"],
            "name": version.get("name", root.get("name", "")),
            "description": version.get("description", root.get("description", "")),
            "category": version.get("category", root.get("category", "")),
            "status": root.get("status", "inactive"),
            "created_at": root.get("created_at", ""),
            "updated_at": root.get("updated_at", ""),
            "route_code": root.get("route_code", ""),
            "lifecycle_status": root.get("lifecycle_status", "active"),
            "current_effective_version_id": root.get("current_effective_version_id"),
            "route_version_id": version.get("id"),
            "route_version": version.get("version"),
            "version_status": version.get("status"),
            "effective_from": version.get("effective_from", ""),
            "effective_to": version.get("effective_to", ""),
            "revision_reason": version.get("revision_reason", ""),
            "version_row_version": version.get("row_version"),
            "open_version_id": open_version.get("id"),
            "open_version": open_version.get("version"),
            "open_version_status": open_version.get("status"),
            "processes": LegacyProcessCompatibilityService._route_items(
                root["id"], version, legacy_route
            ),
        }
        route.update(
            {
                "used_orders": usage.get("used_orders", 0),
                "used_products": usage.get("used_products", 0),
                "is_locked": usage.get("is_locked", False),
            }
        )
        return route

    @staticmethod
    def _route_item_signature(route):
        return [
            {
                field: item.get(field)
                for field in LegacyProcessCompatibilityService.ROUTE_ITEM_COMPARE_FIELDS
            }
            for item in route.get("processes") or []
        ]

    @staticmethod
    def _audit_diff(entity, legacy_payload, versioned_payload, collection, fields):
        if not config.PROCESS_VERSION_COMPAT_AUDIT_ENABLED:
            return
        legacy_rows = legacy_payload.get(collection) or []
        versioned_rows = versioned_payload.get(collection) or []
        legacy_by_id = {int(row["id"]): row for row in legacy_rows}
        versioned_by_id = {int(row["id"]): row for row in versioned_rows}
        legacy_order = [int(row["id"]) for row in legacy_rows]
        versioned_order = [int(row["id"]) for row in versioned_rows]
        field_differences = []
        for entity_id in sorted(set(legacy_by_id) & set(versioned_by_id)):
            legacy = legacy_by_id[entity_id]
            versioned = versioned_by_id[entity_id]
            for field in fields:
                if legacy.get(field) != versioned.get(field):
                    field_differences.append(
                        {
                            "id": entity_id,
                            "field": field,
                            "legacy": legacy.get(field),
                            "versioned": versioned.get(field),
                        }
                    )
            if entity == "routes" and (
                LegacyProcessCompatibilityService._route_item_signature(legacy)
                != LegacyProcessCompatibilityService._route_item_signature(versioned)
            ):
                field_differences.append(
                    {
                        "id": entity_id,
                        "field": "processes",
                        "legacy": LegacyProcessCompatibilityService._route_item_signature(
                            legacy
                        ),
                        "versioned": LegacyProcessCompatibilityService._route_item_signature(
                            versioned
                        ),
                    }
                )
        details = {
            "event": "master_data_compat_diff",
            "entity": entity,
            "legacy_total": legacy_payload.get("total", len(legacy_rows)),
            "versioned_total": versioned_payload.get("total", len(versioned_rows)),
            "missing_from_versioned": sorted(set(legacy_by_id) - set(versioned_by_id)),
            "missing_from_legacy": sorted(set(versioned_by_id) - set(legacy_by_id)),
            "ordering_changed": legacy_order != versioned_order,
            "field_differences": field_differences[:100],
        }
        if any(
            (
                details["legacy_total"] != details["versioned_total"],
                details["missing_from_versioned"],
                details["missing_from_legacy"],
                details["ordering_changed"],
                details["field_differences"],
            )
        ):
            logger.warning(
                "master_data_compat_diff %s",
                json.dumps(details, ensure_ascii=False, sort_keys=True, default=str),
            )

    @staticmethod
    def list_processes(
        legacy_payload,
        *,
        category="",
        search="",
        sort_by="seq_order",
        sort_dir="ASC",
        limit=200,
        offset=0,
        selectable=False,
    ):
        if not config.PROCESS_VERSIONED_QUERY_ENABLED:
            return legacy_payload
        projected = [
            LegacyProcessCompatibilityService._process_projection(root)
            for root in ProcessVersionRepository.roots()
        ]
        if selectable:
            projected = [
                row
                for row in projected
                if row["lifecycle_status"] == "active"
                and row["status"] == "active"
                and row["version_status"] == "published"
            ]
        category_counts = dict(Counter(row["category"] for row in projected))
        if category:
            projected = [row for row in projected if row["category"] == category]
        if search:
            keyword = str(search).casefold()
            projected = [
                row for row in projected if keyword in row["process_name"].casefold()
            ]
        field = "process_name" if sort_by == "name" else sort_by
        reverse = str(sort_dir).upper() == "DESC"
        projected.sort(
            key=lambda row: (
                LegacyProcessCompatibilityService._sort_value(row.get(field)),
                row["id"],
            ),
            reverse=reverse,
        )
        total = len(projected)
        start = max(int(offset or 0), 0)
        if limit is not None:
            projected = projected[start : start + max(int(limit), 0)]
        elif start:
            projected = projected[start:]
        result = {
            "processes": projected,
            "total": total,
            "category_counts": category_counts,
        }
        LegacyProcessCompatibilityService._audit_diff(
            "processes",
            legacy_payload,
            result,
            "processes",
            LegacyProcessCompatibilityService.PROCESS_COMPARE_FIELDS,
        )
        return result

    @staticmethod
    def list_routes(
        legacy_payload,
        *,
        category="",
        search="",
        limit=None,
        offset=0,
        selectable=False,
    ):
        if not config.PROCESS_VERSIONED_QUERY_ENABLED:
            return legacy_payload
        roots = RouteVersionRepository.roots()
        legacy_by_id = {
            int(route["id"]): route for route in legacy_payload.get("routes") or []
        }
        usage_by_id = RouteRepository.get_route_usage_counts(
            [root["id"] for root in roots]
        )
        projected = [
            LegacyProcessCompatibilityService._route_projection(
                root,
                legacy_by_id.get(int(root["id"])),
                usage_by_id.get(int(root["id"]), {}),
            )
            for root in roots
        ]
        if selectable:
            projected = [
                row
                for row in projected
                if row["lifecycle_status"] == "active"
                and row["status"] == "active"
                and row["version_status"] == "published"
            ]
        summary_rows = list(projected)
        if category:
            projected = [row for row in projected if row["category"] == category]
        if search:
            keyword = str(search).casefold()
            projected = [row for row in projected if keyword in row["name"].casefold()]
        projected.sort(
            key=lambda row: (
                LegacyProcessCompatibilityService._sort_value(row.get("created_at")),
                row["id"],
            ),
            reverse=True,
        )
        total = len(projected)
        start = max(int(offset or 0), 0)
        if limit:
            size = max(1, min(int(limit), 200))
            projected = projected[start : start + size]
        elif start:
            projected = projected[start:]
        category_counts = dict(Counter(row["category"] for row in summary_rows))
        result = {
            "routes": projected,
            "total": total,
            "summary": {
                "total_routes": len(summary_rows),
                "category_counts": category_counts,
                "process_nodes_total": sum(
                    len(row.get("processes") or []) for row in summary_rows
                ),
            },
        }
        LegacyProcessCompatibilityService._audit_diff(
            "routes",
            legacy_payload,
            result,
            "routes",
            LegacyProcessCompatibilityService.ROUTE_COMPARE_FIELDS,
        )
        return result

    @staticmethod
    def current_route_for_legacy_apply(route_id):
        if not config.PROCESS_VERSIONED_QUERY_ENABLED:
            return None
        from modules.services.route_version_service import RouteVersionService

        return RouteVersionService.resolve_current_for_business(route_id)
