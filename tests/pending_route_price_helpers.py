"""Factories for exact pending-route price workflow tests."""

import uuid

from modules.repositories.payroll_repository import PayrollRepository
from modules.services.price_version_service import PriceVersionService
from modules.services.process_version_service import ProcessVersionService
from modules.services.route_version_service import RouteVersionService
from tests.test_process_version_workflow import _create_process
from tests.test_route_version_workflow import _create_route


def pending_route_with_prices(client, actor, price_count=2):
    process_versions = []
    for index in range(price_count):
        created = _create_process(client, actor, f"待发布定价工序 {index + 1}")
        with client.application.app_context():
            process_versions.append(
                ProcessVersionService.submit(
                    created["version"]["id"],
                    {
                        "row_version": created["version"]["row_version"],
                        "idempotency_key": (
                            f"pending-price-process-submit-{uuid.uuid4().hex}"
                        ),
                    },
                    actor,
                )
            )
    route_created = _create_route(client, actor, process_versions)
    with client.application.app_context():
        route = RouteVersionService.submit(
            route_created["version"]["id"],
            {
                "row_version": route_created["version"]["row_version"],
                "idempotency_key": f"pending-price-route-submit-{uuid.uuid4().hex}",
            },
            actor,
        )
        prices = [
            create_exact_price_for_route_item(route, item, actor, "1.25")
            for item in route["items"]
        ]
        return route, prices


def route_draft_using_process_status(client, process_status, actor):
    created = _create_process(client, actor, "路线冻结校验工序")
    process_version = created["version"]
    if process_status == "pending_approval":
        with client.application.app_context():
            process_version = ProcessVersionService.submit(
                process_version["id"],
                {
                    "row_version": process_version["row_version"],
                    "idempotency_key": "freeze-check-process-submit",
                },
                actor,
            )
    elif process_status != "draft":
        raise ValueError("test factory supports draft or pending_approval")
    return _create_route(client, actor, [process_version])["version"]


def create_exact_price_for_route_item(route, item, actor, amount):
    binding = PayrollRepository.exact_price_binding(
        route["id"], item["process_version_id"]
    )
    return PriceVersionService.create(
        {
            "route_id": route["process_route_id"],
            "route_version_id": route["id"],
            "process_id": item["process_id"],
            "process_version_id": item["process_version_id"],
            "expected_route_content_digest": binding["route_content_digest"],
            "expected_process_content_digest": binding["process_content_digest"],
            "normal_unit_price": amount,
            "valid_from": "2026-08-24 07:00:00",
            "idempotency_key": f"exact-price-{uuid.uuid4().hex}",
        },
        actor,
    )
