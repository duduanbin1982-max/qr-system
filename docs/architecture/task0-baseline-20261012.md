# Architecture Task 0: Baseline and Boundary Gates

**Date:** 2026-10-12 (Asia/Shanghai)
**Repository:** `qr-system`
**Commit:** `7f271eed01de74b547ab93dd83b2d84495c11bd8`
**Scope:** backend module boundaries, frontend API/import boundaries, and intentional architecture-violation fixtures.

## Frozen baseline

- Python source files: 654 tracked files.
- Frontend source files: 224 tracked files.
- Test files: 253 tracked files.
- Existing service-to-database seams are frozen to:
  - `modules/services/approval_policy_service.py` -> `modules.db_unit_of_work`
  - `modules/services/auth_session_service.py` -> `modules.db`
  - `modules/services/department_service.py` -> `modules.db_unit_of_work`
- Existing middleware SQL access is limited to `modules/middleware/audit.py` while the audit boundary is migrated.

## Gates added

`tests/test_architecture_imports.py` now verifies:

1. Service database imports match the frozen baseline exactly.
2. Middleware SQL access does not expand beyond the existing audit adapter.
3. Nested fixtures detect Service -> database imports.
4. Nested fixtures detect Middleware -> SQL access.

Existing recursive checks remain active for:

- backend import cycles;
- Domain -> Flask/Service/Repository/database dependencies;
- Route -> Repository/database dependencies;
- Repository -> Service and peer Repository dependencies;
- Service -> SQLite, migration, and embedded business SQL;
- pure scheduling allocator database access;
- schedule service direct SQL;
- frontend API facade and import-cycle boundaries.

## Verification

| Check | Result |
|---|---:|
| `python -m pytest -q tests/test_architecture_imports.py` | `27 passed` |
| `npm run check:api` | passed; 34 namespaces, 455 methods |
| `npm run check:imports` | passed; 219 files, 532 internal edges |
| `npm run check:architecture` | passed |
| `git diff --cached --check` | passed |

## Safety boundary

This task changed only architecture tests and this report. It did not modify production code, database data, deployment configuration, or production services. Existing `.brooks-lint-history.json`, temporary replica files, and prior evidence directories remain outside the Task 0 change set.

## Exit criteria

Task 0 is complete when this report and the gate changes are reviewed. Task 1 may then remove the first Service -> database seam while the exact baseline test prevents new seams from appearing elsewhere.
