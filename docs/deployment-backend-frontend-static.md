# Backend and Static Asset Release

`scripts/deploy-backend-frontend-static.sh` is a distinct release scope for a
backend commit plus a frontend build published to `public/static`. It does not
run database migrations, attachment migrations, or restore production database
or attachment data.

## Preconditions

- The launcher and release controls come from an independently reviewed,
  hash-verified overlay (or an already installed production copy). The target
  is a separate, clean worktree exactly at the reviewed merge SHA. A check-only
  run needs the target object in the separate tool repository, not in the
  production repository; execute mode requires it in production before switch.
- Production checkout and `.deployed_commit` match the read-only confirmed
  current SHA; the service is active, healthy, and unfenced.
- Production schema version matches the target's declared schema version.
- `package.json`, `package-lock.json`, Node/npm pins, and Vite configuration
  are unchanged by the target release. Frontend source and backend module
  changes are eligible; supporting tests/docs may accompany them. Migration,
  release-control, and runtime asset changes are rejected.
- The production baseline `c0448bfc945bcfa9c09e94ab1d4bf11f93a3c022`
  has three reviewed support-file exceptions: the inventory view-state test,
  the Task 7 execute bootstrap, and the Task 8 release-control bootstrap.
  Each exception pins both Git entries (existence, mode, type, and blob);
  another baseline, deletion, mode change, or different content is rejected.
  These files accompany the business history; this launcher does not run them.
- The build environment already has the exact pinned Node/npm versions. The
  release path verifies versions and never installs or switches toolchains.

## Read-only Check

Run from the production checkout with a separate target worktree:

```bash
bash scripts/deploy-backend-frontend-static.sh \
  --project-root /home/dubin/qr-system \
  --tool-root /home/dubin/release-tool/target \
  --expected-before <confirmed-production-sha> \
  --target-commit <reviewed-merge-sha> \
  --deployment-key <unique-key> \
  --check-only
```

Check-only fingerprints production state and builds the target assets in an
isolated temporary worktree/cache. It does not alter the production checkout,
database, attachments, `public/static`, write fence, or service state. When the
host's default Node/npm differs from the repository pins, pass the preinstalled
pinned binaries explicitly with `NODE_BIN` and `NPM_BIN`; this path does not
install or switch runtimes.

For the first run, use `scripts/bootstrap_backend_frontend_static_check.py`
exported from its independently reviewed merge and verify its SHA-256 before
starting Python. It accepts only `--check-only`, verifies the production and
tool worktrees plus the approved control files, prepares a temporary launcher
overlay, and removes the temporary target worktree after the check. It does not
install files into the production checkout. Supply the exact tool commit,
target commit, confirmed production baseline, preflight-only key, bootstrap
SHA-256, and the existing pinned Node runtime directory.

## Execute and Recovery Contract

Execution acquires the application write fence, stops the service, verifies
database and attachment backups, and archives the previous static tree. It
builds and hashes the target bundle before the fence, then atomically exchanges
the same-filesystem static directories and switches backend code while the
service remains stopped and fenced. Health, target commit, database version,
unchanged database/attachment fingerprints, and the built asset inventory are
checked before releasing the fence. Durable backups and the deployment
manifest/log are retained.

On failure after switching, rollback restores only the previous backend commit
and static asset tree. It verifies database and attachment fingerprints are
unchanged; it never writes their backups back to production. If rollback or
health verification fails, the service remains stopped and the write fence and
evidence remain in place for operator recovery.

When a code switch fails with the old HEAD still present, the abort path verifies
the actual checkout, deployed marker, and clean worktree before restarting the
old service and again before releasing the fence. A partial checkout or later
code drift leaves the service stopped and the fence retained. A staged static
directory is removed only after its inventory matches the verified target
archive and its exact path is inside the release staging namespace.

## Verification Snapshot (2026-10-22)

- Linux isolated release/bootstrap contracts: **49 passed, 1 deselected** in
  92.59 seconds. The deselected test needs the real repository history and is
  included in the local Windows suite. Linux covers real Git, SQLite, archive
  and directory exchange operations with isolated service/health adapters.
  Scenarios include successful publication, target-health rollback, database
  drift, rollback-health failure, idempotency-key reuse, static archive drift,
  a clean switch failure, a partial checkout, and drift during abort acceptance.
- The expanded Windows release/deployment/architecture contract suite completed
  with **311 passed, 17 skipped** in 592.70 seconds. Platform skips are retained
  explicitly; the separate Linux run above exercises the new real launcher and
  atomic directory exchange paths. The actual-history pin test passed on Windows.
- GitHub merge run `39579679595` had one Windows E2E failure at
  `frontend/tests/e2e/admin-pages.spec.js:98` after 24 passing tests. On
  2026-10-22, the same order-filter test passed, and the complete Windows E2E
  suite passed 25/25 locally on the separately reviewed business-fix branch.
  PR #127 run `39722427124` passed both Ubuntu and Windows frontend checks.
  PR #128 run `39731937270` also passed both platform checks.
  The earlier failure was not reproduced; it is retained here as historical
  evidence rather than treated as an open failure.
- The read-only production observation at 14:18:58 (Asia/Shanghai) was checkout/marker
  `c0448bfc945bcfa9c09e94ab1d4bf11f93a3c022`, with
  `qr-system.service` active. Candidate `a984b77ccab77ef8794e476545092ed974e3ec06`
  is not present in the production repository and predates production commits
  `f8bfa5342ab630a0abeded627801db65ae3aa989` and
  `c0448bfc945bcfa9c09e94ab1d4bf11f93a3c022`. Do not bypass ancestry checks or
  deploy that candidate over those fixes.
- PR #127 merged as `a7db48376478b10ad3aded9814ab30b2bb0cb89d`, preserving
  the shipment-search and order-progress production fixes. PR #128 integrated
  production ancestry and merged as
  **`2955b572ab2087e04f0b26c1b1af37c01979e99e`**. This is the business target:
  production `c0448bf` is its ancestor, and its tree
  `1b14fbaef8ebd5746252e58fc157a2f716ed51ae` is identical to PR #127's merge
  tree. The release-tool commit is a separate descendant, not the business
  commit to install in production.
- A real production `--check-only` has **not** yet been run at this documentation
  checkpoint. Isolated Linux tests do not substitute for it. Merge the separately
  reviewed tools, synchronize them to a clean external tool checkout, reconfirm
  the production SHA, and run the verified check-only bootstrap. Archive the
  result separately with the exact business/tool/production SHAs. This bootstrap
  has no execute mode and makes no production installation or service changes.
