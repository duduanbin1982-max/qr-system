# Approval management repairs A–D

The user approved the four-batch remediation design and automatic implementation,
testing, local review, commits, GitHub pushes, PR creation and CI follow-up.
Approval, merge and production deployment require separate authorization.

Baseline: master 9f3700ac9deb7c428feb86e171d3f30d1ecf2c2a. Each batch branches
independently from that baseline and has a separate PR targeting master.

## A: Resolve role identity before enforcing uniqueness

Keep code-only clients compatible. When a step contains both role ID and code,
both must identify the same active role; do not silently fall back from an invalid
ID to a code. Enforce unique resolved role IDs across all steps. Reject before
revision/step/event persistence, with transaction rollback for any newly created
policy. Preserve the existing validation_error API structure and lifecycle rules.

## B: Record the role used to authorize each decision

The decision's current_role must equal the matched required_role for any accepted
action. Step approver_role and role snapshots use that identity. Test single and
multiple roles, every list permutation, intermediate/final approval, rejection and
unauthorized rollback. Do not rewrite historical audit records.

## C: Use an explicit history pagination contract

Send limit=20 initially, then use returned page/limit/total consistently in history
navigation and display. Commit page state only after a successful response. Keep
the current rows/page on failures; disable navigation while loading. Use request
sequence identity to prevent stale successful or failed responses from replacing
newer results or clearing their loading state. Pending approvals retain their
existing paging contract. Test 10/20/50 sizes, empty/exact/partial last pages,
navigation bounds, failures and out-of-order responses using mounted Vue behavior.

## D: Share visibility for lists and statistics

Reuse the existing list visibility: exclude soft-deleted orders, retain missing
order/work-record rows. Apply it to pending count, overdue count, total and average
processed latency. Keep statuses and API fields unchanged. Share only SQL relation
and visibility fragments within ApprovalRepository, with real SQLite tests for
both visible and excluded populations. No schema or production data changes.

## Verification and handoff

For each batch, demonstrate regression tests fail on the original implementation,
then pass after the minimal repair. Run relevant integration and architecture
checks. Selectively commit source/tests/docs; never stage audit history. Open four
PRs using github remote only. Verify CI against each exact head, then perform a
Brooks review. Do not claim skipped or unexecuted suites passed.
