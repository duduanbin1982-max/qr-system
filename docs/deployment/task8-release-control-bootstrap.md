# Task 8 Release-Control Bootstrap

This one-time bridge is required because the Task 8 target changes the trusted
`scripts/code_only_release.py` policy while production still runs the previous
policy. Its release transition and execute mode must be reviewed independently
before use.

The bridge accepts exactly:

- production baseline `dd97f9ffeee558299d8b83c3f86d86a3097ca962`;
- Task 8 merge plus the release-gate fixture compatibility fix
  `1882fc1af015927041fd341b4b357398460db42d`;
- the exact changed-path and blob manifest embedded in
  `scripts/bootstrap_task8_release_control.py`.

Both modes verify the production checkout, marker, release-tool worktree,
protected runtime files, and exact target tree. `--check-only` creates a
temporary overlay containing the target policy and current production controls,
then runs the normal release checks without changing production state. `--execute`
requires the independently reviewed bootstrap SHA256, distinct positive
operator/approver IDs, and an exclusive durable receipt under
`data/deployments/` before it invokes the existing code-only launcher.

Only the exact policy transition from blob
`f619adedac535e03735f98f40adaa049b6eb9c1b` to
`7fa3364f958b588246b865ab2cbf0da12d2c3a4a` is allowed in the overlay. The
launcher is patched only to use that overlay and is syntax-checked before
invoking the normal code-only release path. The standard launcher retains the
write fence, backup, rollback, and health acceptance state machine.

Neither mode permits database, attachment, or frontend migration. `--check-only`
does not create deployment evidence, write a fence, or stop/start the service.
`--execute` must only be used after its code and exact digest have passed PR
review and merge, a fresh read-only production check succeeds, and a separate
production deployment authorization is in force.
