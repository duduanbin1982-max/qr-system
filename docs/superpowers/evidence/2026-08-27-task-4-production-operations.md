# Task 4 Production Operations Foundation Evidence

**Date:** 2026-08-27  
**Branch:** `codex/task-4-production-operations`  
**Base commit:** `cd459683de7bab1a32c1545ae7cdccc6532e0aa2`  
**Database schema:** unchanged at `user_version=75`

## Scope

- Added `scripts/production_operations.py` as a shared mechanical safety layer.
- Added a read-only SQLite opener with the characterized row factory, foreign-key,
  busy-timeout, query-only, and stable transaction behavior.
- Added file, database, and ordered table-count fingerprints.
- Added atomic JSON evidence writing with fail-closed non-overwrite behavior.
- Added verified online SQLite backup support.
- Added an adapter that invokes the authoritative `backup-db.sh` implementation and verifies
  its result through `deployment_manifest.py`.
- Added a JSON CLI wrapper that preserves the characterized success/failure streams and exit
  codes, including the existing optional indented failure format.

No existing production command delegates to this module in Task 4. Consumer migration remains
Task 5 so that each script group can prove external behavior equivalence independently.

## Authority And Error Boundaries

- `deployment_manifest.py`, `backup-db.sh`, and `rollback-deployment.sh` remain authoritative.
- The foundation reuses deployment-manifest hashing, SQLite integrity checks, backup evidence
  verification, and atomic JSON writing instead of implementing competing rules.
- Operational errors retain an explicit category for argument, backup, and integrity failures.
- The shared layer performs no business authorization, migration choice, service restart,
  rollback decision, feature-flag change, or production-state transition.

## Verification

```text
python -m pytest -q tests/test_production_operations.py \
  tests/test_production_operations_characterization.py
41 passed

python -m pytest -q tests/test_process_v2_operations_scripts.py \
  tests/test_pending_route_price_v074_operations.py \
  tests/test_deployment_contracts.py
36 passed in 21.78s

python -m pytest -q tests/test_architecture_imports.py tests/test_migrations.py
47 passed in 11.73s

python -m pytest -q
1222 passed in 225.33s

npm run check:architecture
API facade check passed: 34 namespaces, 408 unique domain methods
Frontend import cycle check passed: 196 files, 487 internal edges

npm run build
258 modules transformed; production build passed

SECRET_KEY=task-4-schema-check python -c \
  "from modules.migrations import LATEST_VERSION; assert LATEST_VERSION == 75"
passed

git diff --check
passed
```

## Release Boundary

Task 4 adds no migration, schema object, API change, permission change, feature flag, or frontend
runtime change. Production databases, services, attachments, deployed files, and environment
settings were not modified. Push, pull-request creation, merge, Task 5 consumer migration, and
any later production deployment each require their applicable review or explicit authorization.
