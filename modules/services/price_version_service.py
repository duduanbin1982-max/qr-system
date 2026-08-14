"""Approved, time-effective route price versions for payroll."""

from datetime import datetime

from modules.domain.payroll_policy import normalize_timestamp, yuan_to_micros
from modules.repositories.payroll_repository import PayrollRepository
from modules.services import BaseService


class PriceVersionService:
    @staticmethod
    def create(data, actor_user):
        actor_id = actor_user.get("id") if actor_user else None
        actor_name = (actor_user or {}).get("name") or (actor_user or {}).get("username") or "system"
        try:
            route_id = int(data.get("route_id"))
            process_id = int(data.get("process_id"))
            route_version_id = int(data.get("route_version_id"))
            process_version_id = int(data.get("process_version_id"))
        except (TypeError, ValueError) as exc:
            raise ValueError("路线版本和工序版本必须有效") from exc
        normal_micros = data.get("normal_unit_price_micros")
        if normal_micros is None:
            normal_micros = yuan_to_micros(data.get("normal_unit_price"))
        else:
            normal_micros = int(normal_micros)
            if normal_micros <= 0:
                raise ValueError("工价必须大于 0")
        rate = data.get("rework_rate_basis_points")
        configured = 0
        if rate is None and data.get("rework_rate_percent") is not None:
            rate = round(float(data["rework_rate_percent"]) * 100)
        if rate is not None:
            rate = int(rate)
            if not 0 <= rate <= 10000:
                raise ValueError("返工倍率必须在 0 到 10000 之间")
            configured = 1
        valid_from = normalize_timestamp(data.get("valid_from"), "生效时间")
        with BaseService.transaction() as db:
            binding = PayrollRepository.exact_price_binding(
                route_version_id, process_version_id, db
            )
            if binding is None:
                raise ValueError("工序版本不属于该路线版本")
            if binding["route_id"] != route_id or binding["process_id"] != process_id:
                raise ValueError("路线、工序根 ID 与版本归属不一致")
            version_id = PayrollRepository.create_price_version({
                "route_id": route_id, "route_version_id": route_version_id,
                "process_id": process_id, "process_version_id": process_version_id,
                "normal_unit_price_micros": normal_micros,
                "rework_rate_basis_points": rate or 0,
                "rework_rate_configured": configured,
                "valid_from": valid_from, "created_by": actor_id,
                "created_by_name": actor_name, "remark": str(data.get("remark") or "").strip(),
            }, db)
            PayrollRepository.insert_event({
                "event_type": "price_version_created", "operator_id": actor_id, "operator_name": actor_name,
                "payload": {
                    "price_version_id": version_id,
                    "route_id": route_id,
                    "route_version_id": route_version_id,
                    "process_id": process_id,
                    "process_version_id": process_version_id,
                },
            }, db)
            return PayrollRepository.price_version(version_id, db)

    @staticmethod
    def approve(version_id, actor_user, expected_row_version):
        actor_id = actor_user.get("id") if actor_user else None
        actor_name = (actor_user or {}).get("name") or (actor_user or {}).get("username") or "system"
        try:
            expected_row_version = int(expected_row_version)
        except (TypeError, ValueError) as exc:
            raise ValueError("缺少有效的 row_version") from exc
        with BaseService.transaction() as db:
            version = PayrollRepository.price_version(version_id, db)
            if not version:
                raise ValueError("工价版本不存在")
            if version["status"] != "draft":
                raise ValueError("只有草稿工价可以批准")
            if version.get("created_by") == actor_id:
                raise ValueError("工价制单人与审批人必须不同")
            binding = PayrollRepository.exact_price_binding(
                version["route_version_id"], version["process_version_id"], db
            )
            if binding is None:
                raise ValueError("工价版本的路线或工序版本绑定无效")
            if (
                binding["route_version_status"] != "published"
                or binding["process_version_status"] != "published"
            ):
                raise ValueError("只能批准绑定已发布路线和工序版本的工价")
            PayrollRepository.close_prior_price_version(
                version_id,
                version["route_version_id"],
                version["process_version_id"],
                version["valid_from"],
                db,
            )
            PayrollRepository.approve_price_version(version_id, expected_row_version, {
                "approved_by": actor_id, "approved_by_name": actor_name,
            }, db)
            PayrollRepository.insert_event({
                "event_type": "price_version_approved", "operator_id": actor_id, "operator_name": actor_name,
                "payload": {"price_version_id": version_id},
            }, db)
            return PayrollRepository.price_version(version_id, db)

    @staticmethod
    def list_versions(
        route_id=None, status="", route_version_id=None, process_version_id=None
    ):
        return PayrollRepository.list_price_versions(
            route_id,
            status,
            route_version_id=route_version_id,
            process_version_id=process_version_id,
        )

    @staticmethod
    def reference_items():
        return PayrollRepository.list_route_process_references()
