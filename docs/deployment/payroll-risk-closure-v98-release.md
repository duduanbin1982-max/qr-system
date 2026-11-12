# Payroll risk closure V98 release

This release path is limited to the reviewed transition from production
`c369cf212a2054e14cff0d17b76e5501d26a0b06` (schema V97) to business merge
`6e04ec0ffec73ada6df20aded7117240bb74ec09` (schema V98). It does not make
the ordinary backend/static launcher migration-capable.

## Trust and scope

- The installed release-tool checkout must equal the independently reviewed
  tool merge SHA and contain the business target as an ancestor.
- The bootstrap SHA-256 and every launcher/control file are verified against
  that tool merge before execution.
- Both migration entries, five frontend test support files, and the six
  cumulative release-control transitions are pinned by Git mode, type, and
  blob. Generic `frontend/tests/**`, migration, and release-control changes stay
  denied.
- The release migrates only `data/production.db` from V97 to V98. Managed
  attachments are backed up and fingerprinted but are not migrated.

## Read-only preflight

Run the reviewed bootstrap with `--check-only`, the production baseline, target
business SHA, tool merge SHA, approved bootstrap SHA-256, deployment key, and
the preinstalled Node 24.22.0/npm 11.19.1 runtime. The check:

1. verifies the production checkout, deployed marker, health, write-fence
   absence, ancestry, exact Git transitions, schema V97, and free space;
2. creates an online SQLite replica under the system temporary directory;
3. migrates only the replica to V98 and validates integrity, foreign keys,
   required tables, columns, indexes and triggers, preservation of all columns
   and rows that existed at V97, and a second idempotent migration run;
4. builds the target frontend in an isolated target worktree; and
5. removes the replica and target worktree without changing production state.

## Execute contract

The reviewed execution mode acquires the application write fence, waits for the
running V97 service to acknowledge it, stops the user-level systemd service,
and creates verified database, attachment, and current-static backups. It then
switches code and the deployed marker to the business target, migrates the
database to V98, atomically exchanges the built static directory, and starts
Gunicorn.

Writes remain fenced until health reports the target commit, the database is
connected at V98, all required payroll risk-closure schema objects exist,
managed attachments still match the final backup inventory, and the previous
static tree matches its backup. Only then is automatic restore disabled and the
fence released.

## Failure and rollback

Before fence release, any failure stops the service and invokes verified
rollback. The V97 database backup and previous static tree are restored, the
checkout and deployed marker return to the original SHA, and unchanged
attachments are verified. The old service must report the original commit, a
connected database, and the matching deployment-key write fence before writes
are released. If restoration or health verification fails, the service remains
stopped and the write fence, manifest, log, backups, and failure snapshot are
retained for operator recovery.

After successful fenced acceptance and write release, automatic destructive
database rollback is intentionally disabled. A later business correction must
use a separately reviewed forward repair or an explicitly authorized recovery
operation.

## Authorization boundary

The release-tool PR, its CI and its independent review authorize neither merge
nor production execution. After installing an explicitly authorized tool merge,
`--check-only` and production read-only preflight must pass. A fresh maintenance
window, maximum downtime, deployment key, rollback plan, and explicit deployment
authorization are still required before `--execute`.
