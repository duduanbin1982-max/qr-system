from pathlib import Path

from modules.app import app
from modules.db import get_db
from factories import create_material, ensure_process, ensure_test_order


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_template_snapshot_excludes_historical_test_artifacts():
    with app.app_context():
        db = get_db()
        order_count = db.execute(
            "SELECT COUNT(*) FROM orders "
            "WHERE order_no LIKE ? OR (customer = ? AND product_name = ?)",
            ("TEST-%", "Cross Module Customer", "Cross Module Product"),
        ).fetchone()[0]
        user_count = db.execute(
            "SELECT COUNT(*) FROM users WHERE username IN (?, ?) OR employee_no LIKE ?",
            ("testrunner", "testworker", "TEST-%"),
        ).fetchone()[0]
        process_count = db.execute(
            "SELECT COUNT(*) FROM processes WHERE name LIKE ? OR description IN (?, ?)",
            ("Fixture %", "pytest fixture process", "cross module fixture"),
        ).fetchone()[0]
        route_count = db.execute(
            "SELECT COUNT(*) FROM process_routes WHERE name LIKE ? OR description = ?",
            ("Fixture Route %", "cross module fixture"),
        ).fetchone()[0]

    assert order_count == 0, f"template DB leaked {order_count} historical test orders"
    assert user_count == 0, f"template DB leaked {user_count} historical test users"
    assert process_count == 0, f"template DB leaked {process_count} historical test processes"
    assert route_count == 0, f"template DB leaked {route_count} historical test routes"


def test_small_factories_create_only_requested_business_records(client):
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, "Fixture Factory Process")
        order_id = ensure_test_order(db)
        material_id = create_material(db, quantity=25)
        db.commit()

        assert db.execute("SELECT id FROM processes WHERE id = ?", (process_id,)).fetchone()
        assert db.execute("SELECT id FROM orders WHERE id = ?", (order_id,)).fetchone()
        assert db.execute("SELECT quantity FROM materials WHERE id = ?", (material_id,)).fetchone()[0] == 25


def test_conftest_uses_fresh_template_instead_of_generic_scrubbing():
    source = (PROJECT_ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")

    assert "_scrub_fixture_artifacts" not in source
    assert "_table_columns" not in source
