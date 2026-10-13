#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

bash scripts/publish-frontend.sh

if [[ "${1:-}" == "--restart" ]]; then
    python3 -c "from modules.application.operations_facade import OperationsFacade; OperationsFacade.load_environment(); OperationsFacade.initialize_database()"
    python3 -c "from modules.application.operations_facade import OperationsFacade; OperationsFacade.load_environment(); version=OperationsFacade.verify_schema(); print(f'database schema version: {version}')"
    commit="$(git rev-parse --verify HEAD)"
    if [[ ! "$commit" =~ ^[0-9a-f]{40}$ ]]; then
        echo "Invalid deployment commit: $commit" >&2
        exit 1
    fi
    deployed_commit_tmp=".deployed_commit.tmp.$$"
    trap 'rm -f "$deployed_commit_tmp"' EXIT
    printf '%s\n' "$commit" > "$deployed_commit_tmp"
    mv -f "$deployed_commit_tmp" .deployed_commit
    trap - EXIT
    systemctl --user restart qr-system.service
fi
