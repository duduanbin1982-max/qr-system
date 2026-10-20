# Task 9 Acceptance Evidence (2026-10-20)

This record captures the production-replica and focused contract evidence collected on 2026-10-20 (Asia/Shanghai). It contains aggregate counts and digests only; order, employee, and full replay records are intentionally excluded.

## Evidence Status

| Criterion | Status | Evidence |
| --- | --- | --- |
| V096 replica identity and integrity | PASS | Production snapshot SHA-256, `user_version=96`, `quick_check=ok`, and zero foreign-key violations. |
| Formal schedule and reporting facts remain unchanged by trial | PASS | Source snapshot SHA-256 is unchanged before/after the isolated full-queue run; the trial runner also reports unchanged order-process progress and work-record fingerprints. |
| Full active-order isolated planning | PASS | All 129 active orders entered the queue and succeeded; quantity-conservation violations and node conflicts are zero. |
| Business validation of deadline, capacity, and priority inputs | PASS | Scheduling/business owner confirmed all priorities are P3, no orders are expedited, deadline inputs are current, and the snapshot capacity calendar matches current reality. Projected lateness remains an explicit business risk, not a data-integrity failure. |
| Legacy `schedule_runs.result_json` format | PASS | All 123 production rows parse as top-level JSON lists; focused regression test passes. |
| Short write transaction and `STALE_INPUT` behavior | PASS | Planning does not take the immediate write lock; stale generation and replan inputs produce audited failures without publishing. |
| SAVEPOINT and audit atomicity contracts | PASS | Replan SAVEPOINT/evidence-failure tests and required/best-effort audit transaction tests pass. |
| Rollback data and attachment preservation | PASS (isolated) | The real launcher acceptance and forced-health-failure rollback rehearsal passed on Linux with disposable repository/database/attachments. This is not a production rollback drill. |

## V096 Snapshot

- Source host: `192.168.1.8`; production path: `/tmp/task9-evidence-v096-20261020-4af835e.db`.
- Snapshot file timestamp: `2026-10-20 12:32:53 +08:00`; size: `112,943,104` bytes.
- SHA-256: `18105a0e174d59908d1f75a797a2716d7d08ee9f68038d08d770617d279c84e3`.
- The local temporary copy matched this SHA-256 before the run. A read-only SQLite check reported `user_version=96`, `quick_check=ok`, and `0` foreign-key violations.
- Snapshot counts: `schedule_runs=123`, `schedule_revisions=123`, `schedule_revision_items=132`, `order_process_schedules=111`, `order_process_schedule_segments=236`, `work_records=10,912`.
- All `123/123` `schedule_runs.result_json` values parsed as top-level JSON lists.

## Isolated Full-Queue Trial

The runner was `scripts/validate_production_scheduling_v094_final_acceptance.py` at merge SHA `4af835e0242d31769fc03f891ebba3c34792bd58`, with `--expected-version 96`, `--start-date 2026-10-20`, planning time `2026-10-20T13:00:00+08:00`, and isolated key `task9-v096-evidence-20261020-4af835e-01`. It copied the source snapshot to a disposable writable database; the production source was not used as the planning database.

- Source snapshot unchanged: `true`; SHA-256 after the run remained `18105a0e174d59908d1f75a797a2716d7d08ee9f68038d08d770617d279c84e3`.
- Schema: V096 before and after; database integrity `ok`; foreign-key violations `0`.
- Queue: `129/129` active orders; `129` succeeded; `0` blocked and `0` failed.
- Planned operations: `887` total, `557` internal.
- Quantity conservation violations: `0`; serial-split violations: `0`.
- Node conflicts: `0` internal and `0` against existing scheduled work; configured node counts matched, all focus nodes and multi-node splits were exercised.
- Calendar: `341` cross-shift operations, `240` cross-day operations, `52` weekend-spanning operations, `0` weekend segments, and `0` invalid segments.
- External operations: `3`; external capacity violations: `0`.
- The runner's execution fingerprint for order-process progress and work records was identical before and after the trial.
- Historical replay sample: `20/20` succeeded, with `0` blocked operations, quantity violations, or conflicts.
- Delivery risk remains visible: `107/129` orders were projected late, with maximum lateness `65,740` minutes. This is not a node-conflict or quantity-conservation failure, but requires business review before treating the schedule as operationally acceptable.

## Business Input Review

The second read-only aggregate pass used the same snapshot and planning time (`2026-10-20T13:00:00+08:00`); no individual order identifiers or names were retained.

- Active queue: `129`; missing deadlines: `0`.
- Raw and effective priority inputs: all `129` were priority level `3`, not expedited; all stored previous-priority fields matched. `14` rows had a `priority_effective_at` value, with `1` future-effective change at the planning time; its current and previous intent were both P3/non-expedited.
- Projected late: `107`; `27` already had a deadline before the trial date, while `80` had a deadline on or after the trial date but were still projected late.
- Late-order deadline dates ranged from `2026-09-05` to `2026-12-21`; lateness was `690` minutes minimum, `20,980` minutes median, `32,340` minutes at p90, and `65,740` minutes maximum.
- The evaluator treats a deadline as the end of the stated date (`23:59:59`). The trial used configured calendars/capacities from the snapshot. The scheduling/business owner confirmed that the all-P3/non-expedited priorities, deadline dates, and capacity calendar reflect current intent. No formal schedule was changed.

The `107/129` late projection remains an explicit business-risk output for follow-up prioritization; it is not evidence of a snapshot, quantity, or conflict defect.

The source-file SHA comparison covers the entire V096 snapshot, including formal schedule rows and reporting facts. The separate execution fingerprint covers `order_processes` progress fields and `work_records` in the disposable trial database. Planning writes were confined to that trial database.

## Focused Test Results

All commands ran from the Task 9 worktree using Python 3.12.10 and pytest 9.0.3.

| Command | Result |
| --- | --- |
| `python -m pytest -q tests/test_schedule_task3_hotspot.py::test_evidence_stays_outside_legacy_result_list tests/test_schedule_task8_short_write_transaction.py` | `5 passed` |
| `python -m pytest -q tests/test_schedule_pure_planning.py tests/test_audit_writer.py` | `15 passed` |
| `python -m pytest -q tests/test_schedule_replan_use_case.py` | `2 passed` |
| Rollback contract subset: manifest restore, code-only preservation, drift fail-closed, and real-launcher acceptance/rollback | `5 passed` (`3` local contract cases + `2` Linux rehearsal cases) |
| Release/operations/audit/scheduling contract matrix (operations facade and script boundary, deployment and code-only contracts, release/bootstrap gates, evidence protocol, audit transactions, short-write transaction, pure planning, replan, and schedule architecture) | `331 passed, 6 skipped` |

## Same-SHA Full Verification Matrix

All verification below targets merge SHA `4af835e0242d31769fc03f891ebba3c34792bd58`.

| Check | Result |
| --- | --- |
| Full backend test suite | `2114 passed, 6 skipped` |
| Frontend unit tests | `62 files passed, 453 tests passed` |
| E2E tests | `25 passed` |
| Production build | PASS; Node `24.22.0`, npm `11.19.1`, Vite build completed |
| Architecture/API facade/import cycles/frontend layers | PASS; architecture gate, `34 namespaces/455 methods`, `277 files/587 edges`, and `98` layer tests |
| Operations/deployment/rollback/audit/scheduling contract matrix | `331 passed, 6 skipped` |

The passing tests cover the historical result-list shape; deterministic generation and replan summaries; planning outside `BEGIN IMMEDIATE`; stale generation/replan input evidence; replan SAVEPOINT and evidence-failure preservation of the old projection; required-audit rollback; best-effort SAVEPOINT isolation; and concurrent audit writes.

Rollback contract tests verified restoration/preservation of fixture database facts, attachments, and the previous release, including keeping the write fence until rollback evidence is durable. The Linux rehearsal ran the real launcher twice on disposable state: `accepted` produced manifest status `succeeded` and `rollback` produced `rollback_code_only`; both ended with the fence absent only after durable evidence. The accepted fixture switched `aa4367d216ba2b0cbdfceb9662944c6f2807e422` to `aceace66a083d9dd20d70cc7d678803b4bcc360d`; the forced-failure fixture restored `c30e4fcb2f27338e7aaa846d54da137ff8c53497` after testing target `8766efb84ff72567f1ca826d650c77b2591c6ca6`. In both cases the database user version stayed `96`, database logical SHA stayed `ac031a4ba67809edc50793b54b48e349dc0bdac70bb92a519599801117b36867`, attachment manifest SHA stayed `e26e1bc327035de80a7b7ebf1247c66e072582da7340f7386c21f8723c4ae644`, and the frontend release manifest SHA stayed `1b00c7c001a522608e658f638de9ac07381f169ba8a7a72b815817fab08c5a64`. These are isolated test fixtures, not a production rollback drill.

## Remaining Gaps

1. The snapshot remains in the production host's `/tmp` and is not a durable evidence archive. Retain it until the evidence-retention policy is decided; if removing it later, verify the exact path and SHA-256 first.
2. This evidence supplement does not claim a production deployment. The Linux launcher rehearsal used disposable state; a production rollback drill was not performed.
3. The `107/129` projected-late result remains a business prioritization item even though the business owner confirmed the current deadline, priority, and capacity inputs. Shadow planning did not write the formal schedule.
