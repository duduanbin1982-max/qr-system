# Payroll B3 source-drilldown release

This release-tool exception is limited to production baseline
`365811af5fbe31130b50ad85441d4e1754a36667` and business merge
`bbbfdea6fa50ba296cb122cfcd4bffa85ad5e118`. It does not expand the general
frontend-test, migration, or release-control allowlists.

## Exact transition

The launcher validates the complete baseline-to-target path set using the
existing backend/frontend rules. This B3 exception adds only the following
support and cumulative release-control entries; each entry is pinned by Git
mode, object type, and blob:

| Path | Before | Target |
| --- | --- | --- |
| `frontend/tests/unit/payroll-period-control.spec.js` | `100644 blob 305eba2e360ec75e8c2d201e2acf85487d861b01` | `100644 blob e1e38111f11e73fd56198bd21e68c320ed5e6c1f` |
| `scripts/backend_frontend_static_release.py` | `100644 blob 9c06d55aa8cce39a5bac298e208e330b564752a0` | `100644 blob dded15b17456503d40ed609a02036d21c2bb3fb1` |
| `scripts/deploy-backend-frontend-static.sh` | `100644 blob 5c6817665ed341fd855343ed5e1856bd1407bc32` | `100644 blob ebb3670decb56dcb16e184370f217884a2e1d602` |
| `tests/test_backend_frontend_static_release.py` | `100644 blob aadf321dd68e072b9ec82ba8a92fec970fbddfad` | `100644 blob ad8b58a045968e0aa958823cba4039ac48bd0daf` |

Any different baseline or target, extra test path, changed mode/type/blob,
database migration, attachment path, or unrelated release-control change stays
rejected. The target does not change the database schema and this release
performs no database or attachment migration.

## Trust and preflight

The release-tool PR, CI, and review authorize neither merge nor production
execution. After explicit merge authorization, record the actual tool Merge
SHA. Install only that independently reviewed tool merge as the trust root, and
then rerun the real `deploy-backend-frontend-static.sh --check-only` against
the confirmed production baseline and B3 business Merge SHA. The check must
pass its production read-only preflight before any separate deployment
authorization is considered.

## Residual business risk

The B3 review's pagination/snapshot warning remains open: source rows may drift
across pages if the underlying batch is recalculated while a user is browsing.
This release-tool change does not address that behavior; preserve it as an
explicit residual risk during production readiness review.
