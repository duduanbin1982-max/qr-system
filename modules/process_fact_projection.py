"""Shared projections and bindings for versioned process-bearing business facts."""

import json
import logging


logger = logging.getLogger("qr-system.compatibility")


def process_value_sql(
    fact_alias,
    version_alias,
    legacy_alias,
    field="name",
    role="process",
):
    """Return the canonical snapshot -> exact version -> legacy SQL projection."""
    snapshot_suffix = {
        "name": "name_snapshot",
        "code": "code_snapshot",
        "category": "category_snapshot",
    }[field]
    version_column = {
        "name": "name",
        "code": "process_code_snapshot",
        "category": "category",
    }[field]
    legacy_column = {
        "name": "name",
        "code": "process_code",
        "category": "category",
    }[field]
    return (
        f"COALESCE(NULLIF({fact_alias}.{role}_{snapshot_suffix},''),"
        f"NULLIF({version_alias}.{version_column},''),"
        f"{legacy_alias}.{legacy_column},'')"
    )


def route_name_sql(fact_alias, version_alias, legacy_alias):
    """Return the canonical route snapshot projection."""
    return (
        f"COALESCE(NULLIF({fact_alias}.route_name_snapshot,''),"
        f"NULLIF({version_alias}.name,''),{legacy_alias}.name,'')"
    )


def process_version_join(fact_alias, version_alias, role="process"):
    return (
        f"LEFT JOIN process_versions {version_alias} "
        f"ON {version_alias}.id={fact_alias}.{role}_version_id "
    )


def compatible_process_projection(
    db,
    fact_alias,
    version_alias,
    legacy_alias,
    field="name",
    role="process",
):
    """Return projection, optional join, and version-id SQL for Legacy schemas."""
    has_versions = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='process_versions'"
    ).fetchone() is not None
    if has_versions:
        return (
            process_value_sql(
                fact_alias, version_alias, legacy_alias, field=field, role=role
            ),
            process_version_join(fact_alias, version_alias, role=role),
            f"{fact_alias}.{role}_version_id",
        )
    snapshot_suffix = {
        "name": "name_snapshot",
        "code": "code_snapshot",
        "category": "category_snapshot",
    }[field]
    legacy_column = {
        "name": "name",
        "code": "process_code",
        "category": "category",
    }[field]
    return (
        f"COALESCE(NULLIF({fact_alias}.{role}_{snapshot_suffix},''),"
        f"{legacy_alias}.{legacy_column},'')",
        "",
        "NULL",
    )


def route_version_join(fact_alias, version_alias):
    return (
        f"LEFT JOIN process_route_versions {version_alias} "
        f"ON {version_alias}.id={fact_alias}.route_version_id "
    )


def _binding_row(db, query, params):
    row = db.execute(query, params).fetchone()
    return dict(row) if row else None


def capture_process_fact_binding(
    db,
    *,
    order_id=None,
    process_id=None,
    source_work_record_id=None,
    route_id=None,
):
    """Resolve the immutable version binding for a newly created fact."""
    binding = None
    effective_route_id = route_id
    if source_work_record_id:
        binding = _binding_row(
            db,
            "SELECT process_id,process_version_id,process_code_snapshot,"
            "process_name_snapshot,process_category_snapshot,route_id,"
            "route_version_id,route_name_snapshot FROM work_records WHERE id=?",
            (source_work_record_id,),
        )
        if binding and process_id is not None and binding["process_id"] != process_id:
            raise ValueError("来源报工与事实工序不一致")
        if binding:
            effective_route_id = effective_route_id or binding.get("route_id")
            if binding.get("process_version_id") is None:
                binding = None

    if binding is None and order_id is not None and process_id is not None:
        binding = _binding_row(
            db,
            "SELECT op.process_id,op.process_version_id,op.process_code_snapshot,"
            "op.process_name_snapshot,op.process_category_snapshot,"
            "orders.route_id,orders.route_version_id,orders.route_name_snapshot "
            "FROM order_processes op JOIN orders ON orders.id=op.order_id "
            "WHERE op.order_id=? AND op.process_id=?",
            (order_id, process_id),
        )
        if binding:
            effective_route_id = effective_route_id or binding.get("route_id")
            if binding.get("process_version_id") is None:
                binding = None
    if binding is None and effective_route_id is not None and process_id is not None:
        binding = _binding_row(
            db,
            "SELECT item.process_id,item.process_version_id,"
            "process_version.process_code_snapshot,"
            "process_version.name AS process_name_snapshot,"
            "process_version.category AS process_category_snapshot,"
            "route.id AS route_id,route.current_effective_version_id AS route_version_id,"
            "route_version.name AS route_name_snapshot "
            "FROM process_routes route "
            "JOIN process_route_versions route_version "
            "ON route_version.id=route.current_effective_version_id "
            "JOIN process_route_version_items item "
            "ON item.route_version_id=route_version.id AND item.process_id=? "
            "JOIN process_versions process_version ON process_version.id=item.process_version_id "
            "WHERE route.id=?",
            (process_id, effective_route_id),
        )

    if binding is None and process_id is not None:
        binding = _binding_row(
            db,
            "SELECT process.id AS process_id,version.id AS process_version_id,"
            "version.process_code_snapshot,version.name AS process_name_snapshot,"
            "version.category AS process_category_snapshot,NULL AS route_id,"
            "NULL AS route_version_id,'' AS route_name_snapshot "
            "FROM processes process JOIN process_versions version "
            "ON version.id=process.current_effective_version_id WHERE process.id=?",
            (process_id,),
        )

    if process_id is None:
        return {
            "process_id": None,
            "process_version_id": None,
            "process_code_snapshot": "",
            "process_name_snapshot": "",
            "process_category_snapshot": "",
            "route_id": effective_route_id,
            "route_version_id": None,
            "route_name_snapshot": "",
            "version_binding_source": "",
        }
    if not binding or binding.get("process_version_id") is None:
        raise ValueError("工序缺少已发布版本绑定，禁止写入业务事实")
    if effective_route_id is not None and binding.get("route_version_id") is None:
        raise ValueError("工序路线缺少已发布版本绑定，禁止写入业务事实")
    binding["version_binding_source"] = "captured"
    return binding


def prefixed_process_binding(binding, role="process"):
    """Map one canonical binding to a fact role such as target_process."""
    return {
        f"{role}_version_id": binding.get("process_version_id"),
        f"{role}_code_snapshot": binding.get("process_code_snapshot", ""),
        f"{role}_name_snapshot": binding.get("process_name_snapshot", ""),
        f"{role}_category_snapshot": binding.get(
            "process_category_snapshot", ""
        ),
    }


def warn_legacy_fact_rows(table, rows, roles=("process",)):
    """Emit one structured compatibility warning for unversioned returned rows."""
    role_counts = {role: 0 for role in roles}
    for source_row in rows:
        row = dict(source_row)
        for role in roles:
            root_column = f"{role}_id"
            version_column = f"{role}_version_id"
            if root_column in row and row.get(root_column) is not None:
                if version_column not in row or row.get(version_column) is None:
                    role_counts[role] += 1
    role_counts = {role: count for role, count in role_counts.items() if count}
    if role_counts:
        logger.warning(
            json.dumps(
                {
                    "event": "legacy_process_fact_read",
                    "table": table,
                    "count": sum(role_counts.values()),
                    "roles": role_counts,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    return rows
