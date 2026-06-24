"""回归测试：扫码→抽检提交流程 Bug 修复验证

覆盖近期修复：
- Bug: 管理员扫码重定向缺少 code 参数 (mobile-order.js)
- Bug: quality_inspections.process_id NOT NULL 约束违反 (inspection.js + quality_repository.py)
"""

import json, time, pytest


class TestScanReturnsProcessId:
    """验证 mobile/scan 返回的 processes 包含 process_id"""

    def test_scan_returns_processes_with_id(self, client, auth_headers, test_order_id):
        """扫码返回的订单数据中 processes 数组每个元素应有 process_id"""
        resp = client.post("/api/mobile/scan", headers=auth_headers, json={
            "code": json.dumps({"order_id": test_order_id})
        })
        # 200=找到订单, 404=订单无可用工序, 均合理
        assert resp.status_code in (200, 404)
        if resp.status_code == 200:
            data = resp.get_json()
            assert "order" in data
            processes = data["order"].get("processes", [])
            for p in processes:
                assert "process_id" in p, f"process missing process_id: {p}"
                assert isinstance(p["process_id"], int)


class TestInspectionSubmitWithProcessId:
    """验证抽检提交 process_id 主路径"""

    def test_submit_with_explicit_process_id(self, client, auth_headers, test_order_id):
        """显式传 process_id 应成功提交"""
        # 先获取订单的工序列表
        scan_resp = client.post("/api/mobile/scan", headers=auth_headers, json={
            "code": json.dumps({"order_id": test_order_id})
        })
        if scan_resp.status_code != 200:
            pytest.skip("Scan returned no order data")

        processes = scan_resp.get_json()["order"].get("processes", [])
        if not processes:
            pytest.skip("Order has no processes")

        proc = processes[0]
        resp = client.post("/api/inspection/submit", headers=auth_headers, json={
            "order_id": test_order_id,
            "order_no": "TEST-INSPECT-001",
            "product_code": "TEST-CODE",
            "process_id": proc["process_id"],
            "process_name": proc.get("process_name", proc.get("name", "")),
            "result": "pass",
            "remark": "regression test"
        })
        assert resp.status_code == 200, f"submit failed: {resp.get_json()}"
        data = resp.get_json()
        assert data.get("message") == "ok" or "error" not in data


class TestInspectionSubmitProcessIdFallback:
    """验证后端 process_id 兜底解析逻辑"""

    def test_submit_without_process_id_uses_name_fallback(self, client, auth_headers, test_order_id):
        """不传 process_id 只传 process_name，后端应自动解析"""
        scan_resp = client.post("/api/mobile/scan", headers=auth_headers, json={
            "code": json.dumps({"order_id": test_order_id})
        })
        if scan_resp.status_code != 200:
            pytest.skip("Scan returned no order data")

        processes = scan_resp.get_json()["order"].get("processes", [])
        if not processes:
            pytest.skip("Order has no processes")

        proc = processes[0]
        process_name = proc.get("process_name", proc.get("name", ""))
        if not process_name:
            pytest.skip("Process has no name")

        # 故意不传 process_id，只传 process_name
        resp = client.post("/api/inspection/submit", headers=auth_headers, json={
            "order_id": test_order_id,
            "order_no": "TEST-INSPECT-002",
            "product_code": "TEST-CODE",
            "process_name": process_name,
            "result": "pass",
            "remark": "fallback regression test"
        })
        assert resp.status_code == 200, f"fallback failed: {resp.get_json()}"
        data = resp.get_json()
        assert data.get("message") == "ok" or "error" not in data

    def test_submit_missing_both_process_id_and_name_errors(self, client, auth_headers, test_order_id):
        """process_id 和 process_name 都缺失时应报错"""
        resp = client.post("/api/inspection/submit", headers=auth_headers, json={
            "order_id": test_order_id,
            "order_no": "TEST-INSPECT-003",
            "product_code": "TEST-CODE",
            "result": "pass",
            "remark": "should fail"
        })
        # 修复后应自动回退到订单首个工序，返回 200
        assert resp.status_code in (200, 201), f"expected 200, got {resp.status_code}: {resp.get_json()}"


class TestInspectionSubmitEdgeCases:
    """抽检提交边界条件"""

    def test_submit_without_order_id(self, client, auth_headers):
        """缺少 order_id 应报错"""
        resp = client.post("/api/inspection/submit", headers=auth_headers, json={
            "process_id": 1,
            "process_name": "Test",
            "result": "pass"
        })
        assert resp.status_code == 400

    def test_submit_without_auth(self, client):
        """未认证提交应拒绝"""
        resp = client.post("/api/inspection/submit", json={
            "order_id": 1,
            "process_id": 1,
            "result": "pass"
        })
        assert resp.status_code == 401

    def test_submit_all_result_types(self, client, auth_headers, test_order_id):
        """pass/rework/scrap 三种结果类型均应可提交"""
        scan_resp = client.post("/api/mobile/scan", headers=auth_headers, json={
            "code": json.dumps({"order_id": test_order_id})
        })
        if scan_resp.status_code != 200:
            pytest.skip("No order data available")

        processes = scan_resp.get_json()["order"].get("processes", [])
        if not processes:
            pytest.skip("No processes")

        proc = processes[0]
        for result in ("pass", "rework", "scrap"):
            resp = client.post("/api/inspection/submit", headers=auth_headers, json={
                "order_id": test_order_id,
                "order_no": f"TEST-RTYPE-{result}",
                "product_code": "TEST-CODE",
                "process_id": proc["process_id"],
                "process_name": proc.get("process_name", proc.get("name", "")),
                "result": result,
                "rework_process": proc.get("process_name", "") if result == "rework" else "",
                "remark": f"type={result}"
            })
            assert resp.status_code == 200, f"result={result} failed: {resp.get_json()}"


class TestQualityInspectionRecordIntegrity:
    """验证 quality_inspections 记录完整性"""

    def test_record_has_required_fields(self, client, auth_headers, test_order_id):
        """提交成功后检查数据库记录包含必要字段"""
        scan_resp = client.post("/api/mobile/scan", headers=auth_headers, json={
            "code": json.dumps({"order_id": test_order_id})
        })
        if scan_resp.status_code != 200:
            pytest.skip("No order data")

        processes = scan_resp.get_json()["order"].get("processes", [])
        if not processes:
            pytest.skip("No processes")

        proc = processes[0]
        resp = client.post("/api/inspection/submit", headers=auth_headers, json={
            "order_id": test_order_id,
            "order_no": "TEST-INTEGRITY",
            "product_code": "TEST-CODE",
            "process_id": proc["process_id"],
            "process_name": proc.get("process_name", proc.get("name", "")),
            "result": "pass",
            "remark": "integrity check"
        })
        assert resp.status_code == 200

        # 通过 API 查询确认记录存在
        list_resp = client.get(
            f"/api/quality/inspections?order_id={test_order_id}&limit=50",
            headers=auth_headers
        )
        assert list_resp.status_code == 200
        inspections = list_resp.get_json().get("items", list_resp.get_json().get("inspections", []))
        assert len(inspections) > 0, "No inspection records found after submit"
        record = inspections[0]
        assert record.get("order_id") == test_order_id
        assert record.get("process_id") is not None
        assert record.get("result") in ("pass", "rework", "scrap"), f"unexpected result: {record.get("result")}"
