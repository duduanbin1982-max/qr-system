# Full Technical Debt Remediation Design

**Date:** 2026-08-26
**Status:** Approved
**Production baseline:** `cd6f999836de47a78f0b36f9b251c6f1faa47f49`
**Strategy:** Foundation first, behavior preserving, independently accepted and merged stages

## 1. Context

The full Brooks technical debt assessment covered the deployed Flask/Vue production system,
including backend modules, frontend source, production scripts, tests, compatibility paths,
and the active versioning flags. The system retains strong safety foundations: backend and
frontend import cycles are zero, the API facade contract passes, production dependency audit
reported no npm runtime vulnerabilities, and the deployed baseline passed 1026 backend, 140
frontend unit, and 19 end-to-end tests.

The assessment identified six debts:

1. canonical evidence serialization is duplicated across services and production scripts;
2. production scripts duplicate database, backup, evidence, and CLI safety behavior;
3. performance history migration planning is concentrated in a 526-line method;
4. versioned and Legacy paths have no explicit code-retirement schedule;
5. the process-management page owns five dialogs and too much orchestration state;
6. actor identity is propagated and repeatedly parsed as an untyped mapping.

## 2. Goals

- Establish one frozen evidence serialization protocol without changing existing digest bytes.
- Establish one actor identity parser without changing service error contracts or permissions.
- Centralize mechanical production-operation safety behavior while preserving every CLI contract.
- Decompose performance history planning into independently testable pure stages.
- Make Legacy retirement measurable and explicitly approved instead of time-unbounded.
- Split process-management dialogs without changing visible behavior or API call order.
- Keep every stage independently reviewable, deployable, and reversible.

## 3. Non-goals and Hard Boundaries

The first remediation program is behavior preserving. It must not:

- add or modify database migrations, tables, indexes, triggers, or `user_version`;
- change API paths, request schemas, response schemas, error codes, or Chinese messages;
- recalculate or update stored historical digests;
- change feature-flag values or automatically advance a versioning cutover;
- alter business state transitions, permissions, approval separation, or idempotency behavior;
- mix shared foundations, business decomposition, and Legacy deletion in one pull request;
- authorize a GitHub push, merge, production deployment, service restart, or flag change.

If a stage cannot prove behavioral equivalence, it stops and returns to design review.

## 4. Target Architecture

The remediation consists of five independent boundaries.

### 4.1 Evidence Protocol

Create `modules/domain/evidence_protocol.py` with a versioned, frozen interface:

- `canonical_json_v1(value) -> str`
- `sha256_digest_v1(value) -> str`

Version 1 permanently specifies UTF-8, sorted object keys, compact separators, unescaped
Chinese text, and rejection of NaN values. Domain-specific normalization remains in its
own domain module; only final serialization and hashing move to the common protocol.

Existing public helpers remain temporarily as compatibility wrappers. Stored historical
digests are never recomputed. Characterization fixtures must lock the exact output bytes
before any consumer delegates to the common protocol.

### 4.2 Actor Context

Create `modules/domain/actor_context.py` with an immutable
`ActorContext(id, name, role)` and a fail-closed parser. The parser performs no database lookup,
permission inference, role fallback, or administrator substitution.

Existing service `_actor()` functions remain as compatibility adapters during the first pass.
They delegate parsing to the shared component and translate internal parse failures back to the
existing domain exception, error code, and message. HTTP routes keep passing their current user
mapping until all consumers have migrated.

### 4.3 Production Operations

Create `scripts/production_operations.py` for mechanical operational concerns:

- opening read-only SQLite connections;
- invoking and verifying the authoritative backup implementation;
- computing database and evidence fingerprints;
- atomically writing evidence JSON;
- emitting stable CLI success and failure output;
- preserving non-zero failure exit codes.

The existing `deployment_manifest.py`, `backup-db.sh`, and `rollback-deployment.sh` remain the
authoritative backup and rollback implementations. The new module must call them rather than
reimplementing their behavior. Business authorization, migration decisions, and acceptance
rules remain in each command script.

### 4.4 Performance History Planning

`PerformanceHistoryMigrationService` remains the public application entry point and retains
the current repository queries and transaction boundary. New pure policy components handle:

- source classification;
- production-month and cross-month classification;
- quality-source ambiguity detection;
- missing position and target classification;
- manifest assembly and digest input construction.

Repository results are converted to immutable source DTOs, passed through the pure stages, and
converted back to the exact existing result dictionary. Array ordering, stable keys, counters,
07:00 production-month rules, exception classes, and manifest digests remain unchanged.
`_month_plan()` becomes an orchestration method of at most 50 lines and six branches.

### 4.5 Compatibility Retirement and Process UI

Create a read-only retirement register for performance, process, position, and approval-policy
compatibility paths. Each entry records the current stage, owner, latest mismatch result,
observation start, exit thresholds, target removal release, rollback commit, and approval state.
The checker can report only `blocked` or `eligible`; it cannot edit `.env`, write the database,
stop services, or advance a flag.

Split `frontend/src/views/ProcessList.vue` into independently testable dialogs for process
creation, version details, revision creation, rejection, and lifecycle actions. Children receive
state through props and emit user intent. The page and `useProcessVersions` continue to own API
calls, permissions, busy state, toast messages, reload timing, and navigation.

## 5. Data Flow and Compatibility

### 5.1 Evidence

`domain normalization -> canonical_json_v1 -> UTF-8 bytes -> SHA-256`

Old helpers delegate to the new primitive only after byte-for-byte characterization succeeds.
No fallback serializer is permitted.

### 5.2 Actor Identity

`HTTP current-user mapping -> existing service adapter -> ActorContext parser -> service logic`

The first pass may convert `ActorContext` back to the current internal mapping to limit change
spread. No permission or identity semantics move into the parser.

### 5.3 Production Commands

`existing CLI arguments -> existing argparse contract -> shared mechanical operation -> existing business command -> existing JSON and exit code`

Each migrated command is compared with its predecessor for stdout, stderr, exit code, evidence
JSON, database fingerprint, backup evidence, and rollback outcome.

### 5.4 Performance Migration

`existing repository queries -> immutable sources -> pure classifiers -> manifest builder -> existing result mapping`

SQL, query ordering, and transaction ownership remain unchanged. A production database copy is
used to compare every historical production month, not only synthetic fixtures.

### 5.5 Process UI

`page state -> child props -> emitted intent -> page/composable -> existing API`

Children do not import the API facade, permission catalog, router, or global store.

## 6. Error Handling

- Evidence serialization fails explicitly for unsupported objects, NaN, and encoding errors.
- Compatibility wrappers preserve the original exception type and public message.
- Missing, non-numeric, or non-positive actor IDs fail closed.
- Production operations distinguish argument, backup, integrity, business-preflight, restart,
  and rollback failures and never convert them into successful exit codes.
- Operational evidence contains paths, hashes, counts, and error categories, not secrets or
  complete business payloads.
- Performance pure policies never write the database. Any monthly failure aborts the enclosing
  batch transaction and leaves no partial generated month.
- Missing compatibility evidence, an unreadable flag, or an incomplete observation period makes
  a retirement check `blocked`.
- UI children emit commands only; parent code retains error, retry, toast, and busy-state rules.

## 7. Rollback

Each task has its own branch, pull request, merge commit, and rollback target. Because the program
does not include schema migration, ordinary remediation failure uses a code or static-frontend
rollback, not a database restore. Normal business and audit records created after deployment are
retained.

A database restore is considered only when data corruption is proven and separately authorized.
After rollback, verify the deployed commit, service health, database integrity, feature flags,
and the behavior-equivalence baseline. Failure evidence remains immutable.

## 8. Implementation Stages

1. **Task 1 - Characterization tests.** Freeze digest bytes, exceptions, CLI output, performance
   manifests, and process UI behavior.
2. **Task 2 - Evidence protocol.** Introduce `canonical_json_v1` and migrate consumers while
   retaining compatibility wrappers.
3. **Task 3 - ActorContext.** Introduce the immutable value object and migrate duplicated service
   adapters without changing route inputs.
4. **Task 4 - Production operations foundation.** Add shared mechanical safety primitives.
5. **Task 5 - Production script migration.** Move one business-domain script group per PR and
   prove old/new operational equivalence.
6. **Task 6 - Performance history decomposition.** Extract pure planning stages and compare all
   historical production months on a database copy.
7. **Task 7 - Legacy retirement governance.** Add the four retirement records and read-only gate.
8. **Task 8 - Process UI decomposition.** Extract five dialogs and retain the existing workflow.
9. **Task 9 - Full debt reassessment.** Repeat the full Brooks debt scan and record the actual
   result without promising a score in advance.

Tasks 2, 3, and 4 depend on Task 1. Task 5 depends on Task 4. Task 6 depends on Tasks 1 and 2.
Tasks 7 and 8 depend on Task 1. Task 9 requires Tasks 2 through 8 to be complete.

## 9. Test Matrix

### Backend

- all existing 1026 backend tests pass;
- golden evidence serialization and cross-module digest contracts pass;
- ActorContext invalid-input and legacy-exception compatibility tests pass;
- production-operation success, staged failure, and rollback contracts pass;
- all historical performance months produce zero manifest, counter, classification, and digest
  differences against the pre-refactor implementation;
- Python internal import cycles remain zero;
- database `user_version` remains 75.

### Frontend

- all existing 140 unit tests and 19 end-to-end workflows pass;
- component contracts cover all five extracted process dialogs;
- button visibility, permissions, request order, error messages, close behavior, and refresh timing
  match the original page;
- API facade, frontend import-cycle check, and production build pass.

### Code Gates

- `_month_plan()` is no more than 50 lines and six branches;
- canonical evidence serialization has one authoritative implementation;
- actor parsing has one authoritative implementation;
- migrated production scripts contain no local backup verification, atomic evidence writer, or
  generic CLI error wrapper;
- `ProcessList.vue` retains list and orchestration concerns only;
- no new feature flags, database objects, or import cycles are introduced.

## 10. Fixability Summary

| Finding | Tier | Primary target | Required action |
|---|---|---|---|
| Evidence protocol duplication | manual | `modules/domain/evidence_protocol.py` | Freeze and centralize canonical serialization |
| Raw actor mappings | guided | `modules/domain/actor_context.py` | Introduce immutable actor identity and adapters |
| Production script duplication | manual | `scripts/production_operations.py` | Centralize mechanical operational safety |
| Oversized performance planner | manual | `performance_history_migration_service.py` | Extract pure classifiers and manifest builder |
| Unbounded compatibility paths | manual | operations docs and retirement checker | Add measurable exit governance |
| Oversized process page | guided | `frontend/src/views/ProcessList.vue` | Extract five behavior-preserving dialogs |

## 11. Final Acceptance

- Every critical assessment finding has a dedicated commit, tests, and equivalence evidence.
- Backend, frontend unit, end-to-end, architecture, and build checks all pass.
- Production-copy comparisons report zero differences.
- API contracts, error contracts, permissions, database version, and flags are unchanged.
- Every pull request is independently reversible.
- Legacy code is removed only after its gate is satisfied and a separate approval is recorded.
- Production deployment, stop, restart, migration, or feature-flag change always requires a new,
  explicit authorization for the exact merged commit and maintenance window.
