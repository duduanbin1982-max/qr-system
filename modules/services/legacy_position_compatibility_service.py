"""Legacy and versioned read projections for position master data."""

import json
import logging

from modules import config
from modules.repositories.position_repository import PositionRepository
from modules.repositories.position_version_repository import PositionVersionRepository


logger = logging.getLogger("qr-system.compatibility")


class LegacyPositionCompatibilityService:
    COMPARE_FIELDS = ("name", "description", "status", "process_ids")
    MAX_AUDIT_DIFFERENCES = 100

    @staticmethod
    def _versioned_processes(root, legacy_position, process_names):
        version = root.get("current_version")
        if not version:
            return [dict(item) for item in legacy_position.get("processes") or []]
        return [
            {
                "position_id": int(root["id"]),
                "process_id": int(item["process_id"]),
                "process_name": process_names.get(int(item["process_id"]), ""),
            }
            for item in version.get("processes") or []
        ]

    @staticmethod
    def _projection(
        root,
        legacy_position,
        process_names,
        open_versions,
        lifecycle_requests,
        employee_counts,
    ):
        version = root.get("current_version") or {}
        processes = LegacyPositionCompatibilityService._versioned_processes(
            root, legacy_position, process_names
        )
        projected = {
            key: value for key, value in root.items() if key != "current_version"
        }
        projected.update(
            {
                "name": version.get("name", root.get("name", "")),
                "description": version.get(
                    "description", root.get("description", "")
                ),
                "processes": processes,
                "process_ids": [int(item["process_id"]) for item in processes],
                "current_version": version or None,
                "open_version": open_versions.get(int(root["id"])),
                "pending_lifecycle_request": lifecycle_requests.get(
                    int(root["id"])
                ),
                "employee_count": employee_counts.get(int(root["id"]), 0),
            }
        )
        return projected

    @staticmethod
    def _audit_diff(legacy_payload, versioned_payload):
        if not config.POSITION_COMPAT_AUDIT_ENABLED:
            return
        legacy_rows = legacy_payload.get("positions") or []
        versioned_rows = versioned_payload.get("positions") or []
        legacy_by_id = {int(row["id"]): row for row in legacy_rows}
        versioned_by_id = {int(row["id"]): row for row in versioned_rows}
        differences = []
        for position_id in sorted(set(legacy_by_id) & set(versioned_by_id)):
            legacy = legacy_by_id[position_id]
            versioned = versioned_by_id[position_id]
            for field in LegacyPositionCompatibilityService.COMPARE_FIELDS:
                if legacy.get(field) != versioned.get(field):
                    differences.append({"id": position_id, "field": field})
        details = {
            "event": "master_data_compat_diff",
            "entity": "positions",
            "legacy_total": int(legacy_payload.get("total", len(legacy_rows))),
            "versioned_total": int(
                versioned_payload.get("total", len(versioned_rows))
            ),
            "missing_from_versioned": sorted(
                set(legacy_by_id) - set(versioned_by_id)
            )[: LegacyPositionCompatibilityService.MAX_AUDIT_DIFFERENCES],
            "missing_from_legacy": sorted(
                set(versioned_by_id) - set(legacy_by_id)
            )[: LegacyPositionCompatibilityService.MAX_AUDIT_DIFFERENCES],
            "ordering_changed": [int(row["id"]) for row in legacy_rows]
            != [int(row["id"]) for row in versioned_rows],
            "field_differences": differences[
                : LegacyPositionCompatibilityService.MAX_AUDIT_DIFFERENCES
            ],
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
                json.dumps(details, ensure_ascii=False, sort_keys=True),
            )

    @staticmethod
    def list_positions(legacy_payload):
        if not config.POSITION_VERSIONED_QUERY_ENABLED:
            return legacy_payload
        legacy_rows = legacy_payload.get("positions") or []
        position_ids = [int(row["id"]) for row in legacy_rows]
        roots = PositionVersionRepository.roots(position_ids)
        roots_by_id = {int(root["id"]): root for root in roots}
        legacy_by_id = {int(row["id"]): row for row in legacy_rows}
        current_process_ids = {
            int(item["process_id"])
            for root in roots
            for item in (root.get("current_version") or {}).get("processes") or []
        }
        process_names = {
            int(row["id"]): row["name"]
            for row in PositionRepository.find_process_details_by_ids(
                current_process_ids
            )
        }
        open_versions = PositionVersionRepository.open_versions(position_ids)
        lifecycle_requests = PositionVersionRepository.pending_lifecycle_requests(
            position_ids
        )
        employee_counts = PositionRepository.count_active_users_by_positions(
            position_ids
        )
        projected = [
            LegacyPositionCompatibilityService._projection(
                roots_by_id[position_id],
                legacy_by_id[position_id],
                process_names,
                open_versions,
                lifecycle_requests,
                employee_counts,
            )
            for position_id in position_ids
            if position_id in roots_by_id
        ]
        result = {**legacy_payload, "positions": projected}
        LegacyPositionCompatibilityService._audit_diff(legacy_payload, result)
        return result
