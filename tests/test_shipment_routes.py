import pytest

from modules.services.shipment_service import ShipmentService


@pytest.mark.parametrize(
    ("endpoint", "service_method"),
    (
        ("/api/shipments/batch-complete", "batch_complete"),
        ("/api/shipments/batch-delete", "batch_delete"),
    ),
)
@pytest.mark.parametrize(
    ("result", "expected_status"),
    (
        ({"success": [{"id": 1, "shipment_no": "OUT-001"}], "failed": []}, 200),
        ({"success": [{"id": 1, "shipment_no": "OUT-001"}], "failed": [{"id": 2, "error": "冲突"}]}, 207),
        ({"success": [], "failed": [{"id": 2, "error": "冲突"}]}, 409),
    ),
)
def test_batch_shipment_routes_expose_result_status(
    client, auth_headers, monkeypatch, endpoint, service_method, result, expected_status
):
    monkeypatch.setattr(
        ShipmentService,
        service_method,
        lambda ids, current_user: result,
    )

    response = client.post(endpoint, headers=auth_headers, json={"ids": [1, 2]})

    assert response.status_code == expected_status
    assert response.get_json() == result
