from modules.app import app
from modules.db import get_db


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

    assert order_count == 0
    assert user_count == 0
    assert process_count == 0
    assert route_count == 0
