# Architecture Task 1: Authentication Settings Boundary

**Date:** 2026-10-12 (Asia/Shanghai)
**Base commit:** `e5b660e983770b0bfa2b1440a2dd2aee265693cf`
**Scope:** remove the direct authentication-service dependency on `modules.db` without changing session behavior or settings-cache semantics.

## Change

- `AuthSessionService` now reads session settings through the existing `modules.setting_reader` boundary.
- The reader is exposed as an injectable service collaborator for focused behavior tests.
- The frozen Service-to-Database baseline no longer contains `modules/services/auth_session_service.py -> modules.db`.
- Existing cached setting reads remain in use; the authentication path does not add per-request setting-table queries.

## Preserved behavior

- Missing, empty, invalid, negative, or unreadable settings use the configured defaults.
- Absolute session timeout behavior is unchanged.
- Idle timeout and activity-touch throttling are unchanged.
- Session expiration still updates the user token and session state in one transaction.

## Verification

| Check | Result |
|---|---:|
| Authentication and architecture targeted tests | `38 passed` |
| Architecture tests | `27 passed` |
| API facade check | passed; 34 namespaces, 455 methods |
| Frontend import-cycle check | passed; 219 files, 532 internal edges |
| Backend full suite | `1760 passed` |
| `git diff --check` | passed |

## Remaining frozen seams

- `modules/services/approval_policy_service.py -> modules.db_unit_of_work`
- `modules/services/department_service.py -> modules.db_unit_of_work`

These seams remain frozen by the Task 0 ratchet and are not expanded by Task 1.

## Safety boundary

This task does not change database schema, production data, routes, frontend assets, deployment configuration, or the production environment. Local temporary files, historical reports, and `.brooks-lint-history.json` remain outside the Task 1 change set.
