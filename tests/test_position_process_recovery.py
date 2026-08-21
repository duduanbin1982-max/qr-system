import json
from pathlib import Path
import sqlite3


def _recovery_db(path: Path, mappings):
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE positions (
            id INTEGER PRIMARY KEY,
            position_code TEXT NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE processes (
            id INTEGER PRIMARY KEY,
            process_code TEXT NOT NULL,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE position_processes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id INTEGER NOT NULL,
            process_id INTEGER NOT NULL
        );
        """
    )
    db.executemany(
        "INSERT INTO positions(id,position_code,name,created_at) VALUES (?,?,?,?)",
        (
            (2, "POS-0002", "车工", "2026-01-01 07:00:00"),
            (5, "POS-0005", "铣工", "2026-01-01 07:00:00"),
        ),
    )
    db.executemany(
        "INSERT INTO processes(id,process_code,name,category,created_at) VALUES (?,?,?,?,?)",
        tuple(
            (process_id, f"PROC-{process_id:04d}", f"工序{process_id}", "机加工", "2026-01-01 07:00:00")
            for process_id in (3, 4, 6, 7)
        ),
    )
    for position_id, process_ids in mappings.items():
        db.executemany(
            "INSERT INTO position_processes(position_id,process_id) VALUES (?,?)",
            [(position_id, process_id) for process_id in process_ids],
        )
    db.commit()
    db.close()


def test_recovery_accepts_only_exact_backup_evidence(tmp_path):
    from scripts.recover_position_processes import file_sha256, recover

    before_db = tmp_path / "before.db"
    current_db = tmp_path / "current.db"
    _recovery_db(before_db, {2: [3, 4], 5: [6]})
    _recovery_db(current_db, {5: [7]})
    before_hash = file_sha256(before_db)
    current_hash = file_sha256(current_db)

    report = recover(before_db, current_db, output_dir=tmp_path / "evidence")

    assert report["auto_restored"] == [
        {"position_id": 2, "process_ids": [3, 4], "evidence": before_db.name}
    ]
    assert report["manual_review"][0]["reason_code"] == \
        "POSITION_PROCESS_EVIDENCE_CONFLICT"
    assert report["automatic_database_writes"] is False
    assert file_sha256(before_db) == before_hash
    assert file_sha256(current_db) == current_hash
    manifest_path = Path(report["outputs"]["manifest"]["path"])
    csv_path = Path(report["outputs"]["manual_review_csv"]["path"])
    assert manifest_path.is_file()
    assert csv_path.is_file()
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["mode"] == \
        "exact_backup_evidence"


def test_recovery_does_not_accept_changed_position_identity(tmp_path):
    from scripts.recover_position_processes import recover

    before_db = tmp_path / "before.db"
    current_db = tmp_path / "current.db"
    _recovery_db(before_db, {2: [3, 4]})
    _recovery_db(current_db, {})
    db = sqlite3.connect(current_db)
    db.execute("UPDATE positions SET name='已变更岗位' WHERE id=2")
    db.commit()
    db.close()

    report = recover(before_db, current_db, output_dir=tmp_path / "evidence")

    assert report["auto_restored"] == []
    assert report["manual_review"][0]["reason_code"] == \
        "POSITION_IDENTITY_EVIDENCE_CONFLICT"
