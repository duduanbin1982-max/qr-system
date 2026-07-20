#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
install -D -m 0644 "$PROJECT_ROOT/deploy/qr-system.service" "$HOME/.config/systemd/user/qr-system.service"
systemctl --user daemon-reload
systemctl --user enable --now qr-system.service
systemctl --user --no-pager status qr-system.service
