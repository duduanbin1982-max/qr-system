# Task 5 Performance Production Operations Migration Evidence

**Date:** 2026-08-27
**Branch:** `codex/task-5-performance-operations-migration`
**Base commit:** `28d280e68c2fabda03cb8a9468f09d15d9d00c37`
**Database schema:** unchanged at `user_version=75`

## Scope

- Migrated the performance V2 production-script group to
  `scripts/production_operations.py`.
- Preserved the existing helper names as compatibility wrappers.
- Delegated seven read-only SQLite openers, five online backup wrappers, five ordered payroll
  fingerprints, eight file fingerprints, JSON evidence writes, and eight CLI entry points.
- Preserved the frozen payroll table order, CLI stdout/stderr separation, exit codes, success
  indentation, and the replica validator's distinct indented failure JSON.
- Added delegation tests that fail when a compatibility wrapper bypasses the shared primitive.

The migrated command group is:

- `export_performance_v2_review_diff.py`
- `production_performance_v2_apply.py`
- `production_performance_v2_approve.py`
- `production_performance_v2_cutover.py`
- `production_performance_v2_post_cutover_smoke.py`
- `production_performance_v2_preflight.py`
- `production_performance_v2_supervisor_review.py`
- `validate_performance_v57_replica.py`

## Behavior Boundary

- Business authorization, migration decisions, batch lifecycle rules, service restart logic,
  feature-flag handling, arguments, evidence schemas, filenames, and result dictionaries remain
  in their original command scripts.
- Evidence JSON now uses the shared atomic, fail-closed non-overwrite writer.
- Database copies now use the shared verified SQLite online-backup primitive.
- No migration, schema object, API, permission, feature flag, or frontend behavior changed.

## Verification

```text
python -m pytest -q tests/test_production_operations.py \
  tests/test_production_operations_characterization.py
78 passed in 1.51s

python -m pytest -q tests/test_performance_history_migration.py \
  tests/test_deployment_contracts.py
24 passed in 1.08s

python -m pytest -q tests/test_evidence_protocol.py \
  tests/test_evidence_protocol_characterization.py \
  tests/test_performance_v57_account_roles.py
86 passed in 4.19s

python -m pytest -q
1259 passed in 258.88s

npm run check:architecture
API facade check passed: 34 namespaces, 408 unique domain methods
Frontend import cycle check passed: 196 files, 487 internal edges

npm run build
258 modules transformed; production build passed

SECRET_KEY=task-5-schema-check python -c \
  "from modules.migrations import LATEST_VERSION; assert LATEST_VERSION == 75"
passed

python -m compileall -q <eight migrated scripts>
passed

git diff --check
passed
```

## Release Boundary

This is the first Task 5 business-domain migration group. Other production-script domains remain
for separate, independently reviewed changes. No push, pull request, merge, production deployment,
migration execution, service stop/restart, or feature-flag change was performed.
