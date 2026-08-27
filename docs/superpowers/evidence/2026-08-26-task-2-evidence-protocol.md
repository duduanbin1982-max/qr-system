# Task 2 Evidence Protocol Verification

**Date:** 2026-08-26
**Source baseline:** `bb36472ad71cfe55ad8613ae0a1bb6a601be17a6`
**Implementation head before evidence:** `5bf7ba6`
**Database schema:** `user_version=75`
**Scope:** shared evidence serialization and compatibility delegation only; APIs, permissions, migrations, feature flags, CLI arguments, output contracts, and production state unchanged

## Implementation

- Added `modules.domain.evidence_protocol.canonical_json_v1(value)`.
- Added `modules.domain.evidence_protocol.sha256_digest_v1(value)`.
- Migrated 17 characterized serialization wrappers: 2 domain, 7 service, and 8 production-script providers.
- Migrated 11 digest wrappers: 2 domain, 2 service, and 7 production-script providers.
- Kept process and position normalization in their existing domain modules.
- Kept every existing compatibility helper name and added file-relative repository bootstrapping for directly executed scripts.

## Frozen Evidence

- Canonical JSON UTF-8 SHA-256: `b684ca625660639998b74c8d97a06487a7c62f3755a93e590de9b8153a20f1cf`.
- Synthetic history plan SHA-256: `5978dbcd4cecfd76272d60da9ef0557a5fff8503720de8a67e20906119a5c368`.
- Synthetic history month SHA-256: `308b9601d94c8685aa1b873d162b958b486bd3f9a42cc00e06302aff2c6ab9c5`.
- Task 1 canonical text, UTF-8 bytes, digest, ordering, NaN rejection, domain normalization, manifest, CLI, and UI contracts remain unchanged.

## Verification

- Initial Task 1 evidence protocol baseline: PASS, `41 passed`.
- Protocol primitive plus Task 1 evidence contracts: PASS, `46 passed`.
- Domain and service focused migration suite: PASS, `137 passed`.
- Production-script focused migration suite: PASS, `120 passed`.
- Final focused evidence and business safety suite: PASS, `175 passed`.
- Complete backend suite: PASS, `1204 passed`.
- Python architecture and migration suite: PASS, `47 passed`.
- Complete frontend unit suite: PASS, `149 passed` across 35 files.
- Frontend API facade: PASS, 34 namespaces and 408 unique methods.
- Frontend import-cycle check: PASS, 196 files and 487 internal edges, no cycles.
- Frontend production build: PASS, 258 modules transformed.
- Complete end-to-end suite: PASS, `19 passed`.
- Nine migrated production scripts retain direct `--help` execution from outside the repository.
- `git diff --check`: PASS.
- Target-provider duplication scan: PASS; no migrated wrapper directly calls `json.dumps` or `hashlib.sha256`.

## Environment Note

- Python: `3.12.10`.
- Verification used Node.js `25.2.1` and npm `11.6.2`. The project declares Node.js `>=20.19 <21`; all frontend gates passed, but release-toolchain reproduction should use the declared Node.js 20 line.

## Gate

Task 3 ActorContext remediation may start from this branch only after Task 2 is reviewed and integrated. No production deployment is required for the test evidence itself, and any later deployment requires separate authorization for the exact merged commit.
