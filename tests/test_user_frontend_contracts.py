from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_user_list_displays_work_process_column_and_helpers():
    view = (PROJECT_ROOT / "frontend" / "src" / "views" / "UserList.vue").read_text(encoding="utf-8")
    composable = (PROJECT_ROOT / "frontend" / "src" / "composables" / "useUser.js").read_text(encoding="utf-8")

    assert "员工可报工序" in view
    assert "getWorkProcesses(u)" in view
    assert "getWorkProcessTitle(u)" in view
    assert "work_processes" in composable
    assert "position_processes" in composable
    assert "explicit_processes" in composable
    assert "getWorkProcesses" in composable
