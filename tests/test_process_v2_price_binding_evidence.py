from scripts.export_process_v2_price_binding_evidence import classify_price_binding


def test_price_binding_classification_prefers_actual_payroll_usage():
    assert (
        classify_price_binding([12], [{"route_version_id": 11}], [])
        == "bind_to_payroll_route_revision"
    )
    assert (
        classify_price_binding([12, 13], [{"route_version_id": 11}], [])
        == "split_by_payroll_route_revision"
    )


def test_price_binding_classification_requires_review_for_ambiguous_evidence():
    assert (
        classify_price_binding([], [{"route_version_id": 11}], [])
        == "bind_to_order_route_revision"
    )
    assert (
        classify_price_binding(
            [], [{"route_version_id": 11}, {"route_version_id": 12}], []
        )
        == "manual_order_revision_choice"
    )
    assert (
        classify_price_binding([], [], [{"topology_sha256": "a"}])
        == "create_backup_route_revision_and_bind"
    )
    assert classify_price_binding([], [], []) == "manual_no_route_evidence"
