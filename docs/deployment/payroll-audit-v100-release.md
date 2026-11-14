# Payroll audit V100 migration release

This release path is locked to production commit
`6e04ec0ffec73ada6df20aded7117240bb74ec09` at SQLite schema V98 and business
merge `4c662f8b807a82bcaa298f663d49b39a28823d0f` at schema V100. It is a
dedicated migration path; the generic backend/static release gate is unchanged.

## Exact scope

The controller requires the exact path set and Git mode/blob transition from
the V98 production baseline to the V100 business merge. This includes the V99
and V100 migration registry/implementation files, the payroll audit business
changes and tests, and the V98 release-control files that first appear in that
business merge. Every extra, missing, renamed, mode-changed, or byte-changed
path is rejected. The release-tool PR itself is limited to the five V100
controller, launcher, bootstrap, test, and runbook files listed in
`TOOL_CHANGE_PATHS`.

No generic `frontend/tests/**` or migration exception is added. The static
release gate, package/toolchain files, database data, attachments, and unrelated
release controls remain protected. The V99/V100 schema migration applies only
to `data/production.db`; managed attachments are inventoried and verified as
unchanged, never migrated. The deployment separately switches the reviewed
backend/frontend code and static build.

## Read-only preflight

After this tool PR is independently reviewed, merged, and deliberately
installed as the trusted tool commit, run its bootstrap in `--check-only` mode
with the production baseline, business target, tool merge SHA, approved
bootstrap SHA-256, deployment key, and the target Node/npm runtime. The check
fails closed unless:

1. Production checkout and `.deployed_commit` equal the V98 baseline; the
   service is active and healthy, the database is connected at V98, no write
   fence exists, and the production checkout is otherwise clean.
2. The trusted tool contains the business target, has only the reviewed V100
   tool paths relative to that target, and its installed control bytes match
   the approved tool commit.
3. The baseline-to-target Git path set, modes, and blobs match the exact
   reviewed transition; no tracked production data is present in either tree.
4. A read-only SQLite backup is made into a private temporary directory. The
   target worktree runs V99 then V100 against that replica only. The check
   validates SQLite integrity and foreign keys, V100 tables/columns/indexes/
   triggers, preservation of every pre-existing table's columns and row facts,
   and an idempotent second migration pass.
5. The target frontend passes pinned toolchain, API, import, layer, and build
   checks in an isolated worktree using Node 24.22.0/npm 11.19.1.

The preflight removes its temporary database replica, build output, and target
worktree. It does not acquire a production write fence, stop/restart the
service, modify the production database, switch the checkout, or publish files.

## Authorized execute mode

`--execute` is not authorized by the tool PR or by a successful preflight. It
requires a separate deployment authorization, maintenance window, downtime
limit, deployment key, and verified rollback SHA. The launcher then acquires
the application write fence, verifies fenced health, stops the user-level
service, and creates verified database, attachment, and static backups. It
switches code and marker to the business merge, applies V99/V100, exchanges the
static build, and starts the service while writes remain fenced.

Release acceptance requires healthy target-commit responses, connected V100
database, all required V100 schema objects, unchanged attachment inventory,
and verified previous static backup. Only then may the manifest authorize
release of the write fence. Any earlier failure attempts verified restoration
of the V98 database, code/marker, and previous static content. If restoration
or fenced health verification fails, the service remains stopped and the fence,
manifest, log, backups, and failure snapshot are retained for operator recovery.
After the fence is released, automatic destructive database rollback is
disabled; correction requires a separately reviewed forward repair or an
explicitly authorized recovery operation.

The PR, its CI, independent review, and merge authorize neither trust-root
installation nor production deployment. A new real `--check-only` and
production read-only preflight are required after installing the actual tool
merge SHA. Formal deployment requires a later explicit authorization.
