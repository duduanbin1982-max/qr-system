# Task 7 Code-Only Preflight Bootstrap

## Scope

This is a one-time preflight bridge for the Task 7 merge. It has only a
`--check-only` mode. It does not install release controls, create production
backups or audit records, acquire a write fence, stop or start the service, or
change the production checkout, database, attachments, or frontend.

The approved transition is pinned to production baseline
`7f9b5e0c1968eb5913e4f9176efe690741ae38b8` and Task 7 merge
`dd97f9ffeee558299d8b83c3f86d86a3097ca962`. The bootstrap rejects any other
baseline, target, changed path, Git mode, or blob. The complete 12-entry path
and blob allowlist is in `scripts/bootstrap_task7_release_check.py`.

The only change to the existing protected release-control set is
`scripts/deploy-code-only.sh`, whose target blob must be
`98868bc7b612e59bae7b923085a1b8567a60a739`. The target also adds a separately
pinned bootstrap helper. All other production release controls must retain
their baseline Git entries and on-disk bytes. The write-fence runtime paths
must be unchanged, and neither commit may track `data/`.

## Trust Boundary

Before Python is started on the production host, export this bootstrap from its
independently reviewed merge and verify its SHA-256 from the review record. The
bootstrap then verifies the live production HEAD, `.deployed_commit`, clean
worktree except untracked `data/`, target worktree HEAD, exact changed paths,
all target blobs and release-control bytes. It does not import target modules.

The launcher and validator overlay is temporary and outside both worktrees. It
copies the production backup, manifest, rollback, and validation controls, plus
the exact approved target launcher. A narrowly patched validator permits only
that launcher blob; every other release-control check remains active. Patch
point drift fails closed. The target launcher runs only with `--check-only`;
the bootstrap CLI has no execute option.

The existing code-only preflight reads SQLite with `mode=ro`, writes its
consistent snapshot and test worktree under a private temporary directory, runs
the target tests and architecture checks, then removes both temporary areas.
After the check, the bootstrap verifies that the production HEAD and deployed
marker are unchanged. Any failure blocks progression; it is not an authorization
to deploy.

## Verification

Run the bootstrap tests and existing release contracts on the local branch
before approving this bridge. After its merge, record the bootstrap SHA-256,
synchronize the exact Task 7 merge into a separate clean tool worktree, and run
the real production `--check-only` with a unique preflight-only key. A successful
check still requires a separate maintenance window and explicit production
deployment authorization.
