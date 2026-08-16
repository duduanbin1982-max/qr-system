# QR System - Deployment Guide

## Quick Deploy (single command)
```bash
bash /home/dubin/qr-system/deploy.sh
```

## System Info
- **Server**: 192.168.1.8 (Ubuntu)
- **User**: dubin
- **Project**: /home/dubin/qr-system/
- **DB**: SQLite /home/dubin/qr-system/data/production.db
- **Service**: user systemd `qr-system.service` (Gunicorn)

## Directory Structure
```
/home/dubin/qr-system/
├── frontend/          # Vue 3 + Vite (npm run build)
├── modules/           # Python backend (Flask)
│   ├── routes/        # API endpoints
│   ├── services/      # Business logic
│   ├── repositories/  # Database access
│   └── middleware/     # Auth, validation
├── public/            # Static files + SPA build output
│   ├── static/index.html  # Main entry (Vite SPA)
│   ├── mobile.html    # Mobile scanning page
│   └── static/assets/ # Built JS/CSS
├── data/              # SQLite database + backups
├── scripts/           # Utility scripts
│   ├── build.sh       # Frontend build only
│   ├── backup-db.sh   # Database backup
│   └── heartbeat.sh   # Health check
└── docs/              # Documentation
```

## Common Operations
| Task | Command |
|------|---------|
| Validate deploy | `bash deploy.sh --check-only` |
| Build + Deploy | `bash deploy.sh` |
| Build only | `bash scripts/build.sh` |
| Restart service | `systemctl --user restart qr-system` |
| View logs | `journalctl --user -u qr-system -f` |
| Backup DB | `bash scripts/backup-db.sh` |
| DB maintenance | `python3 scripts/db-maintenance.py` |

## Frontend Build
- `vite` directly outputs to `public/static/`
- Flask `/` route serves `public/static/index.html`
- Production deployment must use `bash deploy.sh`; it enforces a clean worktree, tests,
  backup, frontend build, service reload, health verification, and deployed-commit recording.

## Database
- **File**: /home/dubin/qr-system/data/production.db
- **Backups**: /home/dubin/qr-system/data/backups/
- **Schema**: Auto-managed by modules/migrations.py

## Process V2 controlled cutover

Process and route versioning uses a five-stage release. Keep all evidence outside
the Git worktree and run every command from the exact commit being released.

```bash
SYSTEM_ROOT=/home/dubin/qr-system
PROCESS_DB=/home/dubin/qr-system/data/production.db
PROCESS_EVIDENCE=/home/dubin/process-v2-evidence
mkdir -p "$PROCESS_EVIDENCE"

# 1. Read-only source preflight and in-memory v060-v063 simulation.
python3 scripts/production_process_v2_preflight.py \
  --db "$PROCESS_DB" \
  --output-dir "$PROCESS_EVIDENCE/preflight"

# 2. Create a disposable online replica and run the same migration entry used
#    by the production cutover. The destination must not already exist.
python3 scripts/validate_process_v2_replica.py \
  --source-db "$PROCESS_DB" \
  --replica-db "$PROCESS_EVIDENCE/production-v2-replica.db" \
  --evidence "$PROCESS_EVIDENCE/replica-validation.json" \
  --apply --confirm-replica-validation

# 3. Export JSON and UTF-8 CSV review lists. This command never applies fixes.
python3 scripts/export_process_v2_review_diff.py \
  --source-db "$PROCESS_DB" \
  --candidate-db "$PROCESS_EVIDENCE/production-v2-replica.db" \
  --output-dir "$PROCESS_EVIDENCE/review-diff"
```

All blocking differences and manual-review rows must be resolved or explicitly
accepted before the maintenance window. Record these values for each cutover
command; recalculate `PROCESS_DB_SHA256` after the migration stage.

```bash
PROCESS_COMMIT=$(git -C "$SYSTEM_ROOT" rev-parse HEAD)
PROCESS_DB_SHA256=$(sha256sum "$PROCESS_DB" | awk '{print $1}')
PROCESS_PREFLIGHT="$PROCESS_EVIDENCE/preflight/process-v2-preflight-evidence.json"
PROCESS_PREFLIGHT_SHA256=$(sha256sum "$PROCESS_PREFLIGHT" | awk '{print $1}')
PROCESS_OPERATOR="replace-with-real-operator"
```

First stop production writes and migrate. A dry run is the default; the example
below is the explicit write form. The migration command refuses to run while the
user service is active.

```bash
systemctl --user stop qr-system
PROCESS_DB_SHA256=$(sha256sum "$PROCESS_DB" | awk '{print $1}')
python3 scripts/production_process_v2_cutover.py \
  --system-root "$SYSTEM_ROOT" --db "$PROCESS_DB" \
  --output-dir "$PROCESS_EVIDENCE/cutover" --stage migrate \
  --preflight-evidence "$PROCESS_PREFLIGHT" \
  --preflight-sha256 "$PROCESS_PREFLIGHT_SHA256" \
  --target-commit "$PROCESS_COMMIT" \
  --database-sha256 "$PROCESS_DB_SHA256" \
  --operator "$PROCESS_OPERATOR" \
  --idempotency-key "process-v2-migrate-YYYYMMDD" \
  --apply --confirm-production-cutover
systemctl --user start qr-system
```

Then enable exactly one flag per command in this order: `query`,
`compat_audit`, `versioned_write`, `legacy_block`. Each stage atomically updates
`.env`, restarts the user service, checks health and deployed commit, and restores
the previous environment if acceptance fails.

```bash
PROCESS_DB_SHA256=$(sha256sum "$PROCESS_DB" | awk '{print $1}')
python3 scripts/production_process_v2_cutover.py \
  --system-root "$SYSTEM_ROOT" --db "$PROCESS_DB" \
  --output-dir "$PROCESS_EVIDENCE/cutover" --stage query \
  --preflight-evidence "$PROCESS_PREFLIGHT" \
  --preflight-sha256 "$PROCESS_PREFLIGHT_SHA256" \
  --target-commit "$PROCESS_COMMIT" \
  --database-sha256 "$PROCESS_DB_SHA256" \
  --operator "$PROCESS_OPERATOR" \
  --idempotency-key "process-v2-query-YYYYMMDD" \
  --apply --confirm-production-cutover
```

Repeat the command with the next stage and a new idempotency key. Skipping a
stage is rejected. After `legacy_block`, use a short-lived admin token from an
environment variable for the read-only post-cutover smoke test:

```bash
python3 scripts/production_process_v2_post_cutover_smoke.py \
  --system-root "$SYSTEM_ROOT" --db "$PROCESS_DB" \
  --output-dir "$PROCESS_EVIDENCE/post-cutover" \
  --auth-token "$PROCESS_V2_SMOKE_TOKEN"
```

Before versioned writes are enabled, rollback may restore the pre-migration
database and environment backup. After `versioned_write`, never restore an old
database over new V2 facts: disable writes, preserve evidence, and apply a
forward repair.

## Security Notes
- Application secrets are stored in `/home/dubin/qr-system/.env`, which must remain untracked.
- Server and sudo passwords must never be written to source files, shell history, or deployment logs.
- Rotate credentials interactively with `passwd`; use SSH public-key authentication for deployments.
- SSL: Self-signed, browser will show warning

## Health Check
```bash
# Check service status
systemctl --user status qr-system

# Check disk usage
df -h /home/dubin/qr-system/data/

# Test API
curl -k https://localhost/api/auth/info
```
