import importlib.util
import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_cutover_checker():
    script_path = PROJECT_ROOT / "scripts" / "check-quality-evaluation-cutover.py"
    spec = importlib.util.spec_from_file_location("quality_cutover_checker", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cutover_database():
    db = sqlite3.connect(":memory:")
    db.executescript(
        """
        CREATE TABLE process_handoff_reviews (
            id INTEGER PRIMARY KEY,
            status TEXT NOT NULL
        );
        CREATE TABLE process_quality_evaluations (
            id INTEGER PRIMARY KEY,
            source_type TEXT NOT NULL,
            source_handoff_review_id INTEGER,
            status TEXT NOT NULL
        );
        """
    )
    return db


def test_cutover_checker_accepts_fully_mapped_compatible_statuses():
    checker = _load_cutover_checker()
    db = _cutover_database()
    try:
        db.executescript(
            """
            INSERT INTO process_handoff_reviews VALUES (1, 'confirmed');
            INSERT INTO process_handoff_reviews VALUES (2, 'pending');
            INSERT INTO process_quality_evaluations VALUES (10, 'legacy_handoff', 1, 'confirmed');
            INSERT INTO process_quality_evaluations VALUES (20, 'legacy_handoff', 2, 'pending_verification');
            """
        )

        assert checker.cutover_status(db) == {
            "legacy_rows": 2,
            "imported_rows": 2,
            "unmapped_legacy": 0,
            "orphan_imports": 0,
            "status_mismatches": 0,
        }
    finally:
        db.close()


def test_cutover_checker_detects_unmapped_orphaned_and_mismatched_rows():
    checker = _load_cutover_checker()
    db = _cutover_database()
    try:
        db.executescript(
            """
            INSERT INTO process_handoff_reviews VALUES (1, 'confirmed');
            INSERT INTO process_handoff_reviews VALUES (2, 'pending');
            INSERT INTO process_quality_evaluations VALUES (10, 'legacy_handoff', 1, 'confirmed');
            INSERT INTO process_quality_evaluations VALUES (11, 'legacy_handoff', 999, 'confirmed');
            INSERT INTO process_quality_evaluations VALUES (12, 'legacy_handoff', 1, 'pending_verification');
            """
        )

        status = checker.cutover_status(db)
        assert status["unmapped_legacy"] == 1
        assert status["orphan_imports"] == 1
        assert status["status_mismatches"] == 1
    finally:
        db.close()
