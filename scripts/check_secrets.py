#!/usr/bin/env python3
"""Reject tracked credentials and private keys before test or deployment."""

import re
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEXT_LIMIT_BYTES = 2 * 1024 * 1024
SENSITIVE_PATH_NAMES = {".env", ".env.local", ".env.production"}
PATTERNS = (
    (
        "private key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    (
        "sudo password",
        re.compile(r"(?i)\bsudo\s*(?:password|密码)\s*[:=]\s*(?!<|\$\{|redacted\b)\S+"),
    ),
)


def tracked_files():
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=True,
    )
    for raw_path in result.stdout.split(b"\0"):
        if raw_path:
            yield PROJECT_ROOT / raw_path.decode("utf-8")


def find_violations():
    violations = []
    for path in tracked_files():
        relative_path = path.relative_to(PROJECT_ROOT).as_posix()
        if path.name in SENSITIVE_PATH_NAMES:
            violations.append(f"{relative_path}: tracked environment file")
            continue
        if not path.is_file() or path.stat().st_size > TEXT_LIMIT_BYTES:
            continue
        content = path.read_bytes()
        if b"\0" in content:
            continue
        text = content.decode("utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for label, pattern in PATTERNS:
                if pattern.search(line):
                    violations.append(f"{relative_path}:{line_number}: {label}")
    return violations


def main():
    violations = find_violations()
    if violations:
        print("Tracked secret candidates detected:", file=sys.stderr)
        for violation in violations:
            print(f"- {violation}", file=sys.stderr)
        return 1
    print("Tracked secret check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
