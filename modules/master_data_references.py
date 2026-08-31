"""Authoritative process, route and position reference catalog.

Every stable process/route identity and version reference belongs here.  The
catalog drives impact reporting, contract coverage checks and database delete
guards so those three views cannot drift apart.
"""

from dataclasses import dataclass


IMPACT_BLOCKING = "blocking"
IMPACT_INTERNAL = "internal"
DELETE_BLOCK = "block"
DELETE_IGNORE = "ignore"


@dataclass(frozen=True)
class ReferenceSpec:
    entity_type: str
    table: str
    root_columns: tuple[str, ...] = ()
    version_columns: tuple[str, ...] = ()
    csv_columns: tuple[str, ...] = ()
    business_key: str = ""
    business_label: str = ""
    impact_level: str = IMPACT_BLOCKING
    suggested_action: str = ""
    delete_policy: str = DELETE_BLOCK
    where_clause: str = ""
    required_columns: tuple[str, ...] = ()
    block_operations: tuple[str, ...] = ()

    @property
    def columns(self):
        """Legacy alias retained for modules.process_references callers."""
        return self.root_columns


def _process(
    table,
    root_columns=(),
    *,
    version_columns=(),
    csv_columns=(),
    key,
    label,
    impact_level=IMPACT_BLOCKING,
    action="保留原工序并创建修订版",
    delete_policy=DELETE_BLOCK,
):
    return ReferenceSpec(
        entity_type="process",
        table=table,
        root_columns=tuple(root_columns),
        version_columns=tuple(version_columns),
        csv_columns=tuple(csv_columns),
        business_key=key,
        business_label=label,
        impact_level=impact_level,
        suggested_action=action,
        delete_policy=delete_policy,
    )


def _route(
    table,
    root_columns=(),
    *,
    version_columns=(),
    key,
    label,
    impact_level=IMPACT_BLOCKING,
    action="保留原路线并创建修订版",
    delete_policy=DELETE_BLOCK,
):
    return ReferenceSpec(
        entity_type="route",
        table=table,
        root_columns=tuple(root_columns),
        version_columns=tuple(version_columns),
        business_key=key,
        business_label=label,
        impact_level=impact_level,
        suggested_action=action,
        delete_policy=delete_policy,
    )


def _position(
    table,
    root_columns=(),
    *,
    version_columns=(),
    key,
    label,
    impact_level="high",
    action="保留岗位根和历史修订版",
    where_clause="",
    required_columns=(),
    block_operations=("delete",),
):
    return ReferenceSpec(
        entity_type="position",
        table=table,
        root_columns=tuple(root_columns),
        version_columns=tuple(version_columns),
        business_key=key,
        business_label=label,
        impact_level=impact_level,
        suggested_action=action,
        where_clause=where_clause,
        required_columns=tuple(required_columns),
        block_operations=tuple(block_operations),
    )


PROCESS_REFERENCES = (
    _process("approval_config", ("process_id",), key="approval_config", label="审批配置"),
    _process(
        "approval_policies",
        ("process_id",),
        key="approval_policies",
        label="版本化审批策略",
        impact_level=IMPACT_INTERNAL,
        action="由审批策略版本服务维护",
    ),
    _process(
        "approval_policy_compat_audit",
        ("process_id",),
        key="approval_policy_compat_audit",
        label="审批策略兼容审计",
        impact_level=IMPACT_INTERNAL,
        action="保留不可变双读差异证据",
    ),
    _process(
        "material_consumptions",
        ("process_id",),
        version_columns=("process_version_id",),
        key="material_consumptions",
        label="物料消耗记录",
    ),
    _process(
        "order_completion_focus_events",
        ("process_id",),
        version_columns=("process_version_id",),
        key="completion_focus_events",
        label="订单完工关注事件",
    ),
    _process("order_materials", ("process_id",), key="order_materials", label="订单用料"),
    _process(
        "order_process_schedules",
        ("order_process_id", "process_id"),
        version_columns=("route_version_id", "process_version_id"),
        key="order_process_schedules",
        label="订单工序排程",
    ),
    _process(
        "process_capacity_profiles",
        ("process_id",),
        key="process_capacity_profiles",
        label="工序产能配置档案",
        impact_level=IMPACT_INTERNAL,
        action="保留稳定工序根配置",
    ),
    _process(
        "process_production_lines",
        ("process_id",),
        key="process_production_lines",
        label="工序产线池",
    ),
    _process(
        "order_processes",
        ("process_id",),
        version_columns=("process_version_id",),
        key="order_processes",
        label="订单工序",
    ),
    _process(
        "payroll_detail_lines",
        ("process_id",),
        version_columns=("process_version_id",),
        key="payroll_details",
        label="工资明细台账",
    ),
    _process(
        "performance_quality_events",
        ("process_id",),
        version_columns=("process_version_id",),
        key="performance_quality_events",
        label="绩效质量事件",
    ),
    _process(
        "performance_source_facts",
        ("process_id",),
        version_columns=("process_version_id",),
        key="performance_source_facts",
        label="绩效来源事实",
    ),
    _process(
        "position_processes", ("process_id",), key="position_processes", label="岗位工序"
    ),
    _process(
        "position_version_processes",
        ("process_id",),
        key="position_version_processes",
        label="岗位修订版工序",
        impact_level=IMPACT_INTERNAL,
        action="由岗位版本服务维护",
    ),
    _process(
        "process_handoff_reviews",
        ("from_process_id", "to_process_id"),
        version_columns=("from_process_version_id", "to_process_version_id"),
        key="handoff_reviews",
        label="工序交接评价",
    ),
    _process(
        "process_quality_evaluation_task_audits",
        ("target_process_id", "evaluator_process_id"),
        version_columns=(
            "target_process_version_id",
            "evaluator_process_version_id",
        ),
        key="quality_task_audits",
        label="工序质量评价任务审计",
    ),
    _process(
        "process_quality_evaluation_tasks",
        ("target_process_id", "evaluator_process_id"),
        version_columns=(
            "target_process_version_id",
            "evaluator_process_version_id",
        ),
        key="quality_tasks",
        label="工序质量评价任务",
    ),
    _process(
        "process_quality_evaluation_templates",
        ("process_id",),
        key="quality_evaluation_templates",
        label="工序质量评价模板",
    ),
    _process(
        "process_quality_evaluations",
        ("target_process_id", "evaluator_process_id"),
        version_columns=(
            "target_process_version_id",
            "evaluator_process_version_id",
        ),
        key="quality_evaluations",
        label="工序质量评价",
    ),
    _process(
        "process_route_items",
        ("process_id",),
        key="route_items",
        label="工艺路线节点",
    ),
    _process("product_bom", ("process_id",), key="product_bom", label="产品物料清单"),
    _process(
        "product_items", ("current_process_id",), key="product_items", label="在制品当前位置"
    ),
    _process(
        "quality_inspection_plans",
        ("process_id",),
        key="quality_inspection_plans",
        label="质检计划",
    ),
    _process(
        "quality_inspection_tasks",
        ("process_id",),
        version_columns=("process_version_id",),
        key="quality_inspection_tasks",
        label="质检任务",
    ),
    _process(
        "quality_inspections",
        ("process_id",),
        version_columns=("process_version_id",),
        key="quality_inspections",
        label="质量检验记录",
    ),
    _process(
        "quality_nonconformances",
        ("process_id", "responsible_process_id"),
        version_columns=("process_version_id", "responsible_process_version_id"),
        key="quality_nonconformances",
        label="质量不合格项",
    ),
    _process(
        "quality_standards", ("process_id",), key="quality_standards", label="质量标准"
    ),
    _process(
        "rework_records",
        ("process_id",),
        version_columns=("process_version_id",),
        key="rework_records",
        label="返工记录",
    ),
    _process(
        "route_price_history", ("process_id",), key="price_history", label="历史工价记录"
    ),
    _process(
        "route_price_versions",
        ("process_id",),
        version_columns=("process_version_id",),
        key="price_versions",
        label="工价版本",
    ),
    _process("route_prices", ("process_id",), key="current_prices", label="当前工价"),
    _process(
        "scrap_records",
        ("process_id",),
        version_columns=("process_version_id",),
        key="scrap_records",
        label="报废记录",
    ),
    _process("user_processes", ("process_id",), key="user_processes", label="员工工序授权"),
    _process(
        "users", csv_columns=("process_ids",), key="legacy_user_processes", label="历史员工工序授权"
    ),
    _process(
        "work_records",
        ("process_id",),
        version_columns=("process_version_id",),
        key="work_records",
        label="报工记录",
    ),
    _process(
        "work_time_records",
        ("process_id",),
        version_columns=("process_version_id",),
        key="work_time_records",
        label="工时记录",
    ),
    _process(
        "work_time_standards",
        ("process_id",),
        version_columns=("process_version_id",),
        key="work_time_standards",
        label="标准工时",
    ),
    # Version ownership and workflow references are deletion guards, not user-facing impact.
    _process(
        "processes",
        version_columns=("current_effective_version_id",),
        key="current_process_version",
        label="当前有效工序版本",
        impact_level=IMPACT_INTERNAL,
        action="由版本化工序服务维护",
    ),
    _process(
        "process_versions",
        ("process_id",),
        version_columns=("supersedes_version_id",),
        key="process_versions",
        label="工序修订版",
        impact_level=IMPACT_INTERNAL,
        action="由版本化工序服务维护",
    ),
    _process(
        "process_lifecycle_requests",
        ("process_id",),
        key="process_lifecycle_requests",
        label="工序生命周期申请",
        impact_level=IMPACT_INTERNAL,
        action="由版本化工序服务维护",
    ),
    _process(
        "process_version_events",
        ("entity_id",),
        version_columns=("version_id",),
        key="process_version_events",
        label="工序版本事件",
        impact_level=IMPACT_INTERNAL,
        action="保留不可变版本事件",
    ),
    _process(
        "process_route_version_items",
        ("process_id",),
        version_columns=("process_version_id",),
        key="route_version_items",
        label="路线修订版节点",
        impact_level=IMPACT_INTERNAL,
        action="由版本化路线服务维护",
    ),
    _process(
        "master_data_release_process_versions",
        version_columns=("process_version_id",),
        key="release_process_versions",
        label="主数据发布批次工序",
        impact_level=IMPACT_INTERNAL,
        action="保留主数据发布证据",
    ),
    _process(
        "master_data_release_exceptions",
        version_columns=("retained_process_version_id", "replacement_process_version_id"),
        key="release_exceptions",
        label="主数据发布批准例外",
        impact_level=IMPACT_INTERNAL,
        action="保留主数据发布例外证据",
    ),
    _process(
        "process_price_binding_migration_events",
        version_columns=("process_version_id",),
        key="price_binding_migration_events",
        label="历史工价绑定迁移事件",
        impact_level=IMPACT_INTERNAL,
        action="保留不可变迁移审计证据",
    ),
)


ROUTE_REFERENCES = (
    _route(
        "material_consumptions",
        ("route_id",),
        version_columns=("route_version_id",),
        key="material_consumptions",
        label="物料消耗记录",
    ),
    _route(
        "order_completion_focus_events",
        ("route_id",),
        version_columns=("route_version_id",),
        key="completion_focus_events",
        label="订单完工关注事件",
    ),
    _route(
        "orders",
        ("route_id",),
        version_columns=("route_version_id",),
        key="orders",
        label="生产订单",
    ),
    _route(
        "products",
        ("process_route_id", "route_id"),
        key="products",
        label="产品档案",
    ),
    _route(
        "payroll_detail_lines",
        ("route_id",),
        version_columns=("route_version_id",),
        key="payroll_details",
        label="工资明细台账",
    ),
    _route(
        "performance_quality_events",
        ("route_id",),
        version_columns=("route_version_id",),
        key="performance_quality_events",
        label="绩效质量事件",
    ),
    _route(
        "performance_source_facts",
        ("route_id",),
        version_columns=("route_version_id",),
        key="performance_source_facts",
        label="绩效来源事实",
    ),
    _route(
        "process_handoff_reviews",
        ("route_id",),
        version_columns=("route_version_id",),
        key="handoff_reviews",
        label="工序交接评价",
    ),
    _route(
        "process_quality_evaluation_task_audits",
        ("route_id",),
        version_columns=("route_version_id",),
        key="quality_task_audits",
        label="工序质量评价任务审计",
    ),
    _route(
        "process_quality_evaluation_tasks",
        ("route_id",),
        version_columns=("route_version_id",),
        key="quality_tasks",
        label="工序质量评价任务",
    ),
    _route(
        "process_quality_evaluations",
        ("route_id",),
        version_columns=("route_version_id",),
        key="quality_evaluations",
        label="工序质量评价",
    ),
    _route(
        "process_quality_evaluation_templates",
        ("route_id",),
        key="quality_evaluation_templates",
        label="工序质量评价模板",
    ),
    _route(
        "quality_inspection_plans",
        ("route_id",),
        key="quality_inspection_plans",
        label="质检计划",
    ),
    _route(
        "quality_inspection_tasks",
        ("route_id",),
        version_columns=("route_version_id",),
        key="quality_inspection_tasks",
        label="质检任务",
    ),
    _route(
        "quality_inspections",
        ("route_id",),
        version_columns=("route_version_id",),
        key="quality_inspections",
        label="质量检验记录",
    ),
    _route(
        "quality_nonconformances",
        ("route_id",),
        version_columns=("route_version_id",),
        key="quality_nonconformances",
        label="质量不合格项",
    ),
    _route("quality_standards", ("route_id",), key="quality_standards", label="质量标准"),
    _route(
        "route_price_history", ("route_id",), key="price_history", label="历史工价记录"
    ),
    _route(
        "route_price_versions",
        ("route_id",),
        version_columns=("route_version_id",),
        key="price_versions",
        label="工价版本",
    ),
    _route("route_prices", ("route_id",), key="current_prices", label="当前工价"),
    _route(
        "rework_records",
        ("route_id",),
        version_columns=("route_version_id",),
        key="rework_records",
        label="返工记录",
    ),
    _route(
        "scrap_records",
        ("route_id",),
        version_columns=("route_version_id",),
        key="scrap_records",
        label="报废记录",
    ),
    _route(
        "work_time_records",
        ("route_id",),
        version_columns=("route_version_id",),
        key="work_time_records",
        label="工时记录",
    ),
    _route(
        "work_records",
        ("route_id",),
        version_columns=("route_version_id",),
        key="work_records",
        label="报工记录",
    ),
    _route(
        "work_time_standards",
        ("route_id",),
        version_columns=("route_version_id",),
        key="work_time_standards",
        label="标准工时",
    ),
    # Owned nodes protect direct SQL deletion but do not lock normal route editing.
    _route(
        "process_route_items",
        ("route_id",),
        key="route_items",
        label="路线节点",
        impact_level=IMPACT_INTERNAL,
        action="由路线服务随修订版维护",
    ),
    _route(
        "process_routes",
        version_columns=("current_effective_version_id",),
        key="current_route_version",
        label="当前有效路线版本",
        impact_level=IMPACT_INTERNAL,
        action="由版本化路线服务维护",
    ),
    _route(
        "process_route_versions",
        ("process_route_id",),
        version_columns=("supersedes_version_id",),
        key="route_versions",
        label="路线修订版",
        impact_level=IMPACT_INTERNAL,
        action="由版本化路线服务维护",
    ),
    _route(
        "process_route_lifecycle_requests",
        ("process_route_id",),
        key="route_lifecycle_requests",
        label="路线生命周期申请",
        impact_level=IMPACT_INTERNAL,
        action="由版本化路线服务维护",
    ),
    _route(
        "process_route_version_events",
        ("entity_id",),
        version_columns=("version_id",),
        key="route_version_events",
        label="路线版本事件",
        impact_level=IMPACT_INTERNAL,
        action="保留不可变版本事件",
    ),
    _route(
        "process_route_version_items",
        version_columns=("route_version_id",),
        key="route_version_items",
        label="路线修订版节点",
        impact_level=IMPACT_INTERNAL,
        action="由版本化路线服务维护",
    ),
    _route(
        "master_data_release_route_versions",
        version_columns=("route_version_id",),
        key="release_route_versions",
        label="主数据发布批次路线",
        impact_level=IMPACT_INTERNAL,
        action="保留主数据发布证据",
    ),
    _route(
        "master_data_release_exceptions",
        version_columns=("route_version_id",),
        key="release_exceptions",
        label="主数据发布批准例外",
        impact_level=IMPACT_INTERNAL,
        action="保留主数据发布例外证据",
    ),
    _route(
        "process_price_binding_migration_events",
        version_columns=("route_version_id",),
        key="price_binding_migration_events",
        label="历史工价绑定迁移事件",
        impact_level=IMPACT_INTERNAL,
        action="保留不可变迁移审计证据",
    ),
)


POSITION_REFERENCES = (
    _position(
        "users",
        ("position_id",),
        key="active_employees",
        label="启用员工",
        impact_level="blocking",
        action="先完成启用员工调岗",
        where_clause="status = 'active' AND deleted_at IS NULL",
        required_columns=("status", "deleted_at"),
        block_operations=("delete", "retire"),
    ),
    _position(
        "users",
        ("position_id",),
        key="inactive_employees",
        label="停用员工",
        action="保留员工岗位历史",
        where_clause="COALESCE(status, '') <> 'active' AND deleted_at IS NULL",
        required_columns=("status", "deleted_at"),
    ),
    _position(
        "users",
        ("position_id",),
        key="deleted_employees",
        label="已删除员工",
        impact_level="warning",
        action="保留已删除员工岗位历史",
        where_clause="deleted_at IS NOT NULL",
        required_columns=("deleted_at",),
    ),
    _position(
        "user_sessions",
        ("active_position_id",),
        key="active_sessions",
        label="活跃会话",
        impact_level="blocking",
        action="先失效该岗位的活跃会话",
        where_clause="is_active = 1",
        required_columns=("is_active",),
        block_operations=("delete", "retire"),
    ),
    _position(
        "position_processes",
        ("position_id",),
        key="current_position_processes",
        label="当前岗位工序",
        action="删除无引用草稿岗位时随根清理",
        block_operations=(),
    ),
    _position(
        "position_version_processes",
        version_columns=("position_version_id",),
        key="historical_position_processes",
        label="版本化岗位工序",
    ),
    _position(
        "performance_assignment_history",
        ("position_id",),
        version_columns=("position_version_id",),
        key="assignment_history",
        label="绩效岗位分配历史",
    ),
    _position(
        "performance_source_facts",
        ("position_id_snapshot",),
        version_columns=("position_version_id",),
        key="source_facts",
        label="绩效来源事实",
    ),
    _position(
        "performance_score_revisions",
        ("position_id_snapshot",),
        version_columns=("position_version_id_snapshot",),
        key="score_revisions",
        label="绩效评分修订版",
    ),
    _position(
        "performance_position_target_versions",
        ("position_id",),
        version_columns=("position_version_id_snapshot",),
        key="target_versions",
        label="绩效岗位目标版本",
    ),
    _position(
        "work_records",
        ("submit_position_id",),
        version_columns=("submit_position_version_id",),
        key="work_records",
        label="报工记录",
    ),
    # Root ownership and workflow evidence remain deletion guards but are hidden
    # from the business-facing impact categories.
    _position(
        "positions",
        version_columns=("current_effective_version_id",),
        key="current_position_version",
        label="当前有效岗位版本",
        impact_level=IMPACT_INTERNAL,
        action="由岗位版本服务维护",
    ),
    _position(
        "position_versions",
        ("position_id",),
        version_columns=("supersedes_version_id",),
        key="position_versions",
        label="岗位修订版",
        impact_level=IMPACT_INTERNAL,
        action="保留不可变岗位修订版",
    ),
    _position(
        "position_version_events",
        ("position_id",),
        version_columns=("position_version_id",),
        key="position_version_events",
        label="岗位版本事件",
        impact_level=IMPACT_INTERNAL,
        action="保留不可变岗位版本事件",
    ),
    _position(
        "position_lifecycle_requests",
        ("position_id",),
        key="position_lifecycle_requests",
        label="岗位生命周期申请",
        impact_level=IMPACT_INTERNAL,
        action="保留岗位生命周期审批证据",
    ),
)


MASTER_DATA_REFERENCES = PROCESS_REFERENCES + ROUTE_REFERENCES + POSITION_REFERENCES
PROCESS_REFERENCE_TABLES = frozenset(spec.table for spec in PROCESS_REFERENCES)
ROUTE_REFERENCE_TABLES = frozenset(spec.table for spec in ROUTE_REFERENCES)
POSITION_REFERENCE_TABLES = frozenset(spec.table for spec in POSITION_REFERENCES)


# Explicit exceptions must stay narrow and documented.  These columns are roots,
# not references to another process/route identity.
REFERENCE_COLUMN_EXEMPTIONS = frozenset()


def cataloged_reference_columns():
    return {
        (spec.table, column)
        for spec in MASTER_DATA_REFERENCES
        for column in spec.root_columns + spec.version_columns + spec.csv_columns
    }


def registered_position_reference_columns():
    return {
        (spec.table, column)
        for spec in POSITION_REFERENCES
        for column in spec.root_columns + spec.version_columns
    }


def _looks_like_position_reference_column(column):
    return column in {
        "position_id",
        "position_version_id",
        "position_id_snapshot",
        "position_version_id_snapshot",
    } or any(
        column.endswith(suffix)
        for suffix in (
            "_position_id",
            "_position_version_id",
            "_position_id_snapshot",
            "_position_version_id_snapshot",
        )
    )


def _looks_like_reference_column(column):
    return column in {
        "process_id",
        "process_version_id",
        "route_id",
        "route_version_id",
        "process_route_id",
    } or any(
        column.endswith(suffix)
        for suffix in (
            "_process_id",
            "_process_version_id",
        )
    ) or _looks_like_position_reference_column(column)


def discover_position_reference_columns(db):
    discovered = set()
    tables = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    for row in tables:
        table = row[0]
        for column_row in db.execute(f'PRAGMA table_info("{table}")').fetchall():
            column = column_row[1]
            if _looks_like_position_reference_column(column):
                discovered.add((table, column))
    return discovered


def find_unregistered_reference_columns(db):
    registered = cataloged_reference_columns()
    missing = []
    tables = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ).fetchall()
    for row in tables:
        table = row[0]
        for column_row in db.execute(f'PRAGMA table_info("{table}")').fetchall():
            column = column_row[1]
            pair = (table, column)
            if (
                _looks_like_reference_column(column)
                and pair not in registered
                and pair not in REFERENCE_COLUMN_EXEMPTIONS
            ):
                missing.append(pair)
    return missing


__all__ = [
    "DELETE_BLOCK",
    "DELETE_IGNORE",
    "IMPACT_BLOCKING",
    "IMPACT_INTERNAL",
    "MASTER_DATA_REFERENCES",
    "POSITION_REFERENCES",
    "POSITION_REFERENCE_TABLES",
    "PROCESS_REFERENCES",
    "PROCESS_REFERENCE_TABLES",
    "REFERENCE_COLUMN_EXEMPTIONS",
    "ROUTE_REFERENCES",
    "ROUTE_REFERENCE_TABLES",
    "ReferenceSpec",
    "cataloged_reference_columns",
    "discover_position_reference_columns",
    "find_unregistered_reference_columns",
    "registered_position_reference_columns",
]
