# Approval Management Repairs Implementation Plan

**Goal:** Resolve the four reproduced approval-management findings in independent PRs.

**Architecture:** Keep the existing route/service/domain/repository boundaries.
Resolve policy role identity in the service; keep decision selection in the pure
domain; centralize history state in the composable and visibility in the repository.

**Tech Stack:** Python/Flask/SQLite/pytest, Vue/Vitest, Node 24.22.0/npm 11.19.1.

## Global Constraints

- Execute shell commands using Git Bash.
- Base all four branches on master 9f3700ac9deb7c428feb86e171d3f30d1ecf2c2a.
- Do not approve/merge/deploy or push to origin (production SSH remote).
- Keep .brooks-lint-history.json unstaged and preserve existing entries.
- Keep API fields, role-code-only callers and missing-order visibility compatible.

## A: Role identity

- [ ] Add tests/test_approval_policy_role_validation.py using real revisions/steps.
  Assert ValidationError for conflicting IDs/codes and duplicate resolved roles;
  compare policy/revision/step/event counts before and after rejected calls.
- [ ] Run `python -m pytest tests/test_approval_policy_role_validation.py -q` on old code.
- [ ] Add `_resolve_steps(steps, db)` to ApprovalPolicyService: active ID lookup,
  explicit ID/code consistency, code-only lookup, resolved ID uniqueness. Call
  before create_revision persistence. Keep normalization in approval_policy.py.
- [ ] Run the new tests plus test_approval_policy.py and approval workflow tests.
- [ ] Review, selectively commit `fix(approvals): validate resolved policy roles`.

## B: Decision audit role

- [ ] Add permutation/action/level tests to test_approval_workflow_policy.py and
  real approval_steps assertions in test_approval_workflow.py.
- [ ] Run these tests against old code and capture failures.
- [ ] Replace arbitrary set selection with `current_role=required_role` only after
  membership validation. Keep service logging and role snapshots consistent.
- [ ] Run workflow/service/serial-backfill approval tests and architecture checks.
- [ ] Review, selectively commit `fix(approvals): record matched decision role`.

## C: History pagination

- [ ] Add frontend/tests/unit/ApprovalPageHistory.spec.js with mounted API stubs,
  deferred responses and returned limit/page/total assertions.
- [ ] Run the file against old code and capture failures.
- [ ] Introduce historyLimit, historyTotalPages, historyRequest sequence and
  changeHistoryPage(offset); expose these from useApprovalPage. Template consumes
  those values, never mutates page before a successful response, and disables
  navigation while historyLoading is true.
- [ ] Run the new spec, Task2FApplicationLayers.spec.js, all frontend unit tests,
  frontend layer/API/import gates and build using the pinned runtime.
- [ ] Review, selectively commit `fix(approvals): honor history pagination state`.

## D: Statistics visibility

- [ ] Add tests/test_approval_statistics.py using an in-memory SQLite connection.
  Cover all statuses, deleted/active/missing orders, overdue boundaries and averages.
- [ ] Run against old code and capture failures.
- [ ] Extract ApprovalRepository SQL FROM/visibility constants shared by list/count
  and all aggregate queries; qualify columns, preserve response fields.
- [ ] Run the new tests, approval integrations and architecture pytest suite.
- [ ] Review, selectively commit `fix(approvals): align statistics visibility`.

## PR and combined acceptance

- [ ] Push each branch to github, open a master-targeting PR and attach its URL.
- [ ] Build a local combined verification branch, run the complete backend suite
  and relevant frontend suites, without merging master or changing production.
- [ ] Verify four required CI checks on each exact head; inspect real workflow
  logs/artifacts, then conduct formal review and append only local audit history.
- [ ] Report actual passed/skipped results and any remaining CI/review blocker.
