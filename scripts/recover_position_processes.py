#!/usr/bin/env python3
"""Build a position/process recovery manifest from exact backup evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def open_read_only(path: str | Path) -> sqlite3.Connection:
    source = Path(path).resolve()
    if not source.is_file():
        raise RuntimeError(f"database does not exist: {source}")
    db = sqlite3.connect("file:" + source.as_posix() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA query_only=ON")
    return db


def load_manifest(value: str | Path | dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {"auto_restored": [], "manual_review": []}
    if isinstance(value, dict):
        return value
    path = Path(value).resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid recovery manifest: {path.name}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("recovery manifest must contain a JSON object")
    return payload


def unresolved_manual_items(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    resolved = {"accepted", "closed", "resolved"}
    items = manifest.get("manual_review") or manifest.get("unresolved_items") or []
    if not isinstance(items, list):
        raise RuntimeError("recovery manifest manual review items must be a list")
    return [
        item
        for item in items
        if not isinstance(item, dict)
        or str(item.get("resolution_status") or "open").strip().lower() not in resolved
    ]


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in db.execute(f'PRAGMA table_info("{table}")')}


def _require_schema(db: sqlite3.Connection, label: str) -> None:
    required = {
        "positions": {"id", "name"},
        "processes": {"id", "name"},
        "position_processes": {"position_id", "process_id"},
    }
    for table, columns in required.items():
        actual = _columns(db, table)
        missing = sorted(columns - actual)
        if missing:
            raise RuntimeError(
                f"{label} database is missing {table} columns: {', '.join(missing)}"
            )


def _identity_rows(
    db: sqlite3.Connection, table: str, candidates: tuple[str, ...]
) -> dict[int, dict[str, Any]]:
    columns = _columns(db, table)
    selected = ["id", *(column for column in candidates if column in columns)]
    quoted = ",".join(f'"{column}"' for column in selected)
    return {
        int(row["id"]): {column: row[column] for column in selected}
        for row in db.execute(f'SELECT {quoted} FROM "{table}" ORDER BY id').fetchall()
    }


def _mappings(db: sqlite3.Connection) -> dict[int, list[int]]:
    result: dict[int, list[int]] = {}
    for row in db.execute(
        "SELECT position_id,process_id FROM position_processes "
        "ORDER BY position_id,process_id"
    ).fetchall():
        result.setdefault(int(row["position_id"]), []).append(int(row["process_id"]))
    return {position_id: sorted(set(process_ids)) for position_id, process_ids in result.items()}


def _manual_item(
    position_id: int,
    before_ids: list[int],
    current_ids: list[int],
    reason_code: str,
    evidence: str,
) -> dict[str, Any]:
    return {
        "position_id": position_id,
        "before_process_ids": before_ids,
        "current_process_ids": current_ids,
        "reason_code": reason_code,
        "resolution_status": "open",
        "evidence": evidence,
    }


def _write_outputs(output_dir: Path, document: dict[str, Any]) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "position-process-recovery-manifest.json"
    review_path = output_dir / "position-process-manual-review.csv"
    manifest_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    fields = (
        "position_id",
        "before_process_ids",
        "current_process_ids",
        "reason_code",
        "resolution_status",
        "evidence",
    )
    with review_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in document["manual_review"]:
            writer.writerow(
                {
                    **item,
                    "before_process_ids": json.dumps(item["before_process_ids"]),
                    "current_process_ids": json.dumps(item["current_process_ids"]),
                }
            )
    return {
        "manifest": {"path": str(manifest_path), "sha256": file_sha256(manifest_path)},
        "manual_review_csv": {
            "path": str(review_path),
            "sha256": file_sha256(review_path),
        },
    }


def recover(
    before_db: str | Path,
    current_db: str | Path,
    *,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Compare two read-only databases and emit only exactly evidenced mappings."""

    before_path = Path(before_db).resolve()
    current_path = Path(current_db).resolve()
    if before_path == current_path:
        raise ValueError("backup evidence and current database must be different files")
    before_state = {"sha256": file_sha256(before_path), "size": before_path.stat().st_size}
    current_state = {"sha256": file_sha256(current_path), "size": current_path.stat().st_size}
    before = open_read_only(before_path)
    current = open_read_only(current_path)
    try:
        _require_schema(before, "backup evidence")
        _require_schema(current, "current")
        before_positions = _identity_rows(
            before, "positions", ("position_code", "name", "created_at")
        )
        current_positions = _identity_rows(
            current, "positions", ("position_code", "name", "created_at")
        )
        before_processes = _identity_rows(
            before, "processes", ("process_code", "name", "category", "created_at")
        )
        current_processes = _identity_rows(
            current, "processes", ("process_code", "name", "category", "created_at")
        )
        before_mappings = _mappings(before)
        current_mappings = _mappings(current)
    finally:
        before.close()
        current.close()

    auto_restored: list[dict[str, Any]] = []
    manual_review: list[dict[str, Any]] = []
    unchanged = 0
    evidence_name = before_path.name
    for position_id in sorted(set(before_positions) | set(current_positions)):
        before_ids = before_mappings.get(position_id, [])
        current_ids = current_mappings.get(position_id, [])
        if before_positions.get(position_id) is None:
            continue
        if current_positions.get(position_id) is None:
            if before_ids:
                manual_review.append(
                    _manual_item(
                        position_id,
                        before_ids,
                        current_ids,
                        "POSITION_EVIDENCE_TARGET_MISSING",
                        evidence_name,
                    )
                )
            continue
        if before_ids == current_ids:
            unchanged += 1
            continue
        if before_positions[position_id] != current_positions[position_id]:
            manual_review.append(
                _manual_item(
                    position_id,
                    before_ids,
                    current_ids,
                    "POSITION_IDENTITY_EVIDENCE_CONFLICT",
                    evidence_name,
                )
            )
            continue
        missing_process_identity = any(
            process_id not in before_processes or process_id not in current_processes
            for process_id in before_ids
        )
        conflicting_process_identity = any(
            before_processes.get(process_id) != current_processes.get(process_id)
            for process_id in before_ids
            if process_id in before_processes and process_id in current_processes
        )
        if missing_process_identity:
            reason = "POSITION_PROCESS_EVIDENCE_MISSING"
        elif conflicting_process_identity or current_ids:
            reason = "POSITION_PROCESS_EVIDENCE_CONFLICT"
        else:
            auto_restored.append(
                {
                    "position_id": position_id,
                    "process_ids": before_ids,
                    "evidence": evidence_name,
                }
            )
            continue
        manual_review.append(
            _manual_item(position_id, before_ids, current_ids, reason, evidence_name)
        )

    if (
        file_sha256(before_path) != before_state["sha256"]
        or before_path.stat().st_size != before_state["size"]
        or file_sha256(current_path) != current_state["sha256"]
        or current_path.stat().st_size != current_state["size"]
    ):
        raise RuntimeError("read-only recovery analysis changed an evidence database")

    document = {
        "status": "review_required" if manual_review else "ready",
        "mode": "exact_backup_evidence",
        "automatic_database_writes": False,
        "before_database": {"name": before_path.name, **before_state},
        "current_database": {"name": current_path.name, **current_state},
        "auto_restored": auto_restored,
        "manual_review": manual_review,
        "unchanged_position_count": unchanged,
    }
    outputs = _write_outputs(Path(output_dir).resolve(), document)
    return {**document, "outputs": outputs}


def apply_exact_recovery_manifest(
    db: sqlite3.Connection, manifest: dict[str, Any]
) -> list[dict[str, Any]]:
    """Apply generated auto mappings to a disposable replica only."""

    if manifest.get("mode") != "exact_backup_evidence":
        raise RuntimeError("recovery mappings require an exact backup evidence manifest")
    if unresolved_manual_items(manifest):
        raise RuntimeError("recovery manifest still contains unresolved manual review items")
    applied = []
    for item in manifest.get("auto_restored") or []:
        position_id = int(item["position_id"])
        process_ids = sorted(set(int(value) for value in item.get("process_ids") or []))
        if not process_ids or not str(item.get("evidence") or "").strip():
            raise RuntimeError(f"invalid exact recovery item for position {position_id}")
        existing = [
            int(row[0])
            for row in db.execute(
                "SELECT process_id FROM position_processes WHERE position_id=? "
                "ORDER BY process_id",
                (position_id,),
            ).fetchall()
        ]
        if existing:
            if existing == process_ids:
                continue
            raise RuntimeError(
                f"position {position_id} process mappings changed after recovery evidence"
            )
        if db.execute("SELECT 1 FROM positions WHERE id=?", (position_id,)).fetchone() is None:
            raise RuntimeError(f"recovery position does not exist: {position_id}")
        placeholders = ",".join("?" for _ in process_ids)
        found = {
            int(row[0])
            for row in db.execute(
                f"SELECT id FROM processes WHERE id IN ({placeholders})", process_ids
            ).fetchall()
        }
        if found != set(process_ids):
            raise RuntimeError(f"recovery process does not exist for position {position_id}")
        for process_id in process_ids:
            db.execute(
                "INSERT INTO position_processes(position_id,process_id) VALUES (?,?)",
                (position_id, process_id),
            )
        applied.append(
            {
                "position_id": position_id,
                "process_ids": process_ids,
                "evidence": item["evidence"],
            }
        )
    return applied


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a read-only exact-evidence position/process recovery manifest"
    )
    parser.add_argument("--before-db", required=True)
    parser.add_argument("--current-db", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        report = recover(args.before_db, args.current_db, output_dir=args.output_dir)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
