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
