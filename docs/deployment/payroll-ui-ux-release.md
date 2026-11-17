# Payroll UI/UX release

This release-tool exception is limited to production baseline
96f8d3baf4e170ae5c0fce95f280ba077b956101 and business merge
8da168bde3bd2d51bff5594f7b40aa17f71809f9. It does not broaden the general
frontend-test, migration, attachment, database, or release-control allowlists.

## Exact transition

The launcher validates the complete backend/frontend path set using the
existing rules. This exception adds only the reviewed payroll UI/UX tests and
the cumulative release-control update, each pinned by Git mode, object type,
and blob:

| Path | Before | Target |
| --- | --- | --- |
| frontend/tests/unit/payroll-period-control.spec.js | 100644 blob 5056f2aa6313f5e3ded81b7a6ee1a2898495c62d | 100644 blob 2d5161850c0968536b71d959dbf829772998a600 |
| frontend/tests/unit/payroll-ui-ux.spec.js | absent | 100644 blob 16ec5c3f934a745c2100ec5c8dec5373053737bb |
| scripts/backend_frontend_static_release.py | 100644 blob a949c6f14d1f2850b19aa2f31bbdd81120dca8c0 | 100644 blob 3f62605467a3b2a24afbc56352a352d0163bb020 |

Any different baseline or target, extra frontend test path, changed
mode/type/blob, database migration, attachment path, or unrelated
release-control change remains rejected.

## Trust and preflight

The release-tool PR, CI, and review authorize neither production execution nor
deployment. After explicit merge authorization, record the actual tool Merge
SHA, install only that independently reviewed tool merge as the trust root,
and rerun the real deploy-backend-frontend-static.sh --check-only against
the confirmed production baseline and business Merge SHA. Production Node/npm
must satisfy the repository-pinned 24.22.0/11.19.1 toolchain before the
static build is accepted.

This release changes backend/frontend code and reviewed test support only; it
does not migrate the database or attachments.
