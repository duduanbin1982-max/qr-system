"""ScanHelperService 隔离单元测试 — 核心方法 mock DB 验证"""

import pytest
from unittest.mock import MagicMock, patch


def _make_row(row_dict):
    """模拟 sqlite3.Row：支持下标和 .keys()"""
    mock = MagicMock()
    mock.__getitem__.side_effect = lambda k: row_dict[k]
    mock.get.side_effect = lambda k, d=None: row_dict.get(k, d)
    mock.keys.return_value = row_dict.keys()
    mock.values.return_value = row_dict.values()
    # 让 in 操作符生效
    mock.__contains__.side_effect = lambda k: k in row_dict
    return mock


# ═══════════════════════════════════════════════════════
# check_duplicate_normal_report — 返回 row 或 None
# ═══════════════════════════════════════════════════════

class TestCheckDuplicateNormalReport:

    @patch("modules.services.scan_helper_service.ScanHelperService._db")
    def test_serial_dup_found_returns_row(self, mock_db):
        """序列号重复 → 返回非 None（调用方据此发 409）"""
        from modules.services.scan_helper_service import ScanHelperService
        mock_db.return_value.execute.return_value.fetchone.return_value = {"id": 99}
        result = ScanHelperService.check_duplicate_normal_report(1, 10, "SN-001", 100)
        assert result is not None

    @patch("modules.services.scan_helper_service.ScanHelperService._db")
    def test_serial_no_dup_returns_none(self, mock_db):
        """序列号无重复 → 返回 None"""
        from modules.services.scan_helper_service import ScanHelperService
        mock_db.return_value.execute.return_value.fetchone.return_value = None
        result = ScanHelperService.check_duplicate_normal_report(1, 10, "SN-NEW", 100)
        assert result is None

    @patch("modules.services.scan_helper_service.ScanHelperService._db")
    def test_non_serial_user_dup_found_returns_row(self, mock_db):
        """非序列号 + 同用户同工序重复 → 返回非 None"""
        from modules.services.scan_helper_service import ScanHelperService
        mock_db.return_value.execute.return_value.fetchone.return_value = {"id": 42}
        result = ScanHelperService.check_duplicate_normal_report(1, 10, None, 100)
        assert result is not None

    @patch("modules.services.scan_helper_service.ScanHelperService._db")
    def test_non_serial_no_dup_returns_none(self, mock_db):
        """非序列号无重复 → 返回 None"""
        from modules.services.scan_helper_service import ScanHelperService
        mock_db.return_value.execute.return_value.fetchone.return_value = None
        result = ScanHelperService.check_duplicate_normal_report(1, 10, None, 100)
        assert result is None


# ═══════════════════════════════════════════════════════
# is_last_process
# ═══════════════════════════════════════════════════════

class TestIsLastProcess:

    @patch("modules.services.scan_helper_service.ScanHelperService._db")
    def test_is_last_process_true(self, mock_db):
        """MAX(seq_order) == 当前 seq_order → True"""
        from modules.services.scan_helper_service import ScanHelperService
        mock_cursor = MagicMock()
        # 第1次 execute: SELECT MAX(seq_order) → {"max_seq": 5}
        # 第2次 execute: SELECT seq_order → {"seq_order": 5}
        mock_cursor.fetchone.side_effect = [{"max_seq": 5}, {"seq_order": 5}]
        mock_db.return_value.execute.return_value = mock_cursor
        assert ScanHelperService.is_last_process(1, 10) is True

    @patch("modules.services.scan_helper_service.ScanHelperService._db")
    def test_is_last_process_false(self, mock_db):
        """MAX(seq_order) > 当前 seq_order → False"""
        from modules.services.scan_helper_service import ScanHelperService
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [{"max_seq": 5}, {"seq_order": 3}]
        mock_db.return_value.execute.return_value = mock_cursor
        assert ScanHelperService.is_last_process(1, 10) is False

    @patch("modules.services.scan_helper_service.ScanHelperService._db")
    def test_is_last_process_no_max_row(self, mock_db):
        """工序不存在 → False"""
        from modules.services.scan_helper_service import ScanHelperService
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_db.return_value.execute.return_value = mock_cursor
        assert ScanHelperService.is_last_process(1, 999) is False


# ═══════════════════════════════════════════════════════
# get_prev_incomplete_processes
# ═══════════════════════════════════════════════════════

class TestGetPrevIncompleteProcesses:

    @patch("modules.services.scan_helper_service.ScanHelperService._db")
    def test_has_prev_incomplete(self, mock_db):
        """前置有未完成工序 → 返回列表"""
        from modules.services.scan_helper_service import ScanHelperService
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {"seq_order": 1, "process_name": "下料"},
            {"seq_order": 2, "process_name": "焊接"},
        ]
        mock_db.return_value.execute.return_value = mock_cursor
        result = ScanHelperService.get_prev_incomplete_processes(1, 3)
        assert len(result) == 2
        assert result[0]["process_name"] == "下料"

    @patch("modules.services.scan_helper_service.ScanHelperService._db")
    def test_no_prev_incomplete(self, mock_db):
        """无前置未完成工序 → 空列表"""
        from modules.services.scan_helper_service import ScanHelperService
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_db.return_value.execute.return_value = mock_cursor
        result = ScanHelperService.get_prev_incomplete_processes(1, 1)
        assert result == []


# ═══════════════════════════════════════════════════════
# check_process_order
# ═══════════════════════════════════════════════════════

class TestCheckProcessOrder:

    @patch("modules.services.scan_helper_service.ScanHelperService._db")
    @patch("modules.db.get_setting")
    def test_sequential_blocks_skip(self, mock_get_setting, mock_db):
        """顺序模式 + 有前置未完成 → 阻止"""
        from modules.services.scan_helper_service import ScanHelperService
        mock_get_setting.return_value = "sequential"
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"seq_order": 1, "process_name": "下料"}]
        mock_db.return_value.execute.return_value = mock_cursor
        error, status = ScanHelperService.check_process_order(1, 3)
        assert error is not None
        assert "下料" in error["error"]
        assert status == 400

    @patch("modules.services.scan_helper_service.ScanHelperService._db")
    @patch("modules.db.get_setting")
    def test_out_of_order_allows_skip(self, mock_get_setting, mock_db):
        """乱序模式 → 允许跳过"""
        from modules.services.scan_helper_service import ScanHelperService
        mock_get_setting.return_value = "out_of_order"
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"seq_order": 1, "process_name": "下料"}]
        mock_db.return_value.execute.return_value = mock_cursor
        error, status = ScanHelperService.check_process_order(1, 3)
        assert error is None
        assert status is None

    @patch("modules.services.scan_helper_service.ScanHelperService._db")
    @patch("modules.db.get_setting")
    def test_sequential_no_prev_ok(self, mock_get_setting, mock_db):
        """顺序模式 + 无前置未完成 → 通过"""
        from modules.services.scan_helper_service import ScanHelperService
        mock_get_setting.return_value = "sequential"
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_db.return_value.execute.return_value = mock_cursor
        error, status = ScanHelperService.check_process_order(1, 1)
        assert error is None


# ═══════════════════════════════════════════════════════
# get_order_processes
# ═══════════════════════════════════════════════════════

class TestGetOrderProcesses:

    @patch("modules.services.scan_helper_service.ScanHelperService._db")
    def test_returns_processes_with_ids_and_names(self, mock_db):
        """工序列表包含 process_id 和 process_name"""
        from modules.services.scan_helper_service import ScanHelperService
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {"process_id": 10, "process_name": "下料", "seq_order": 1, "completed": 5},
            {"process_id": 20, "process_name": "焊接", "seq_order": 2, "completed": 3},
        ]
        mock_db.return_value.execute.return_value = mock_cursor
        result = ScanHelperService.get_order_processes(1)
        assert len(result) == 2
        for p in result:
            assert "process_id" in p
            assert "process_name" in p
