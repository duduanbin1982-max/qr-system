# Task 1 Behavior Characterization Baseline

**Date:** 2026-08-26
**Source production baseline:** `cd6f999836de47a78f0b36f9b251c6f1faa47f49`
**Database schema:** `user_version=75`
**Scope:** tests and evidence only; production code, APIs, permissions, state machines, migrations, and feature flags unchanged

## Frozen Contracts

- Canonical JSON UTF-8 SHA-256: `b684ca625660639998b74c8d97a06487a7c62f3755a93e590de9b8153a20f1cf`
- Synthetic history plan SHA-256: `5978dbcd4cecfd76272d60da9ef0557a5fff8503720de8a67e20906119a5c368`
- Synthetic history month SHA-256: `308b9601d94c8685aa1b873d162b958b486bd3f9a42cc00e06302aff2c6ab9c5`
- Actor adapters preserve the exact `id/name/role` mapping and `ValidationError("操作人不能为空")` contract.
- Performance production commands preserve read-only SQLite, backup, payroll fingerprint, stdout, stderr, and exit-code behavior.
- `ProcessList` preserves creation, version editing, submit, approve, reject, revision, lifecycle, permission, toast, and reload behavior.

## Verification

- Baseline backend suite before characterization: PASS, `1026 passed`.
- Baseline frontend unit suite before characterization: PASS, `140 passed`.
- Baseline end-to-end suite before characterization: PASS, `19 passed`.
- Focused backend characterization and related safety suite: PASS, `178 passed`.
- Complete backend suite after characterization: PASS, `1162 passed`.
- Python architecture and migration suite: PASS, `47 passed`; `LATEST_VERSION=75`.
- Complete frontend unit suite after characterization: PASS, `149 passed`.
- Frontend API facade inventory: PASS, 34 namespaces and 408 methods.
- Frontend import-cycle check: PASS, 196 files and 487 edges, no cycles.
- Frontend production build: PASS.
- Complete end-to-end suite after characterization: PASS, `19 passed`.
- `git diff --check`: PASS.

## Environment Note

- Python: `3.12.10`.
- Verification used Node.js `25.2.1` and npm `11.6.2`. The project declares Node.js `>=20.19 <21`; all unit, architecture, build, and E2E gates passed, but release-toolchain reproduction should use the declared Node.js 20 line.

## Gate

Remediation Tasks 2 through 8 may proceed only while these contracts remain green. Any intentional contract change requires separate design review and approval.
