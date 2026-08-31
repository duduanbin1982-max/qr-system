# Task 3 ActorContext Remediation Evidence

**Date:** 2026-08-27  
**Branch:** `codex/task-3-actor-context`  
**Base commit:** `0715e51e1eedd97576f87bd5c55670d9c6c9a3d6`  
**Database schema:** unchanged at `user_version=75`

## Scope

- Added the immutable `ActorContext(id, name, role)` value object.
- Added one fail-closed `parse_actor_context()` implementation.
- Delegated the seven characterized versioned-service actor adapters to the shared parser.
- Kept route inputs and the legacy normalized mapping returned by each adapter unchanged.

## Compatibility Result

- Valid string and integer IDs retain the existing `int()` normalization.
- Blank names retain the existing `username` fallback.
- Names and roles retain whitespace trimming and empty-role behavior.
- The characterized `True -> 1` ID behavior remains unchanged.
- Missing, non-numeric, zero, and negative IDs still surface as
  `ValidationError("操作人不能为空")` with code `validation_error` from service adapters.
- The shared parser performs no database lookup, permission inference, role fallback, or
  administrator substitution.

## Verification

```text
python -m pytest -q tests/test_actor_context.py tests/test_actor_context_characterization.py
72 passed in 0.89s

python -m pytest -q
1212 passed in 229.26s

npm run check:architecture
API facade check passed: 34 namespaces, 408 unique domain methods
Frontend import cycle check passed: 196 files, 487 internal edges

git diff --check
passed
```

## Release Boundary

This task adds no migration, schema object, API change, permission change, feature flag, or
business-state transition. No production database, service, attachment, or environment setting
was modified while producing this evidence. Push, pull-request creation, merge, and any later
production deployment require their own explicit authorization.
