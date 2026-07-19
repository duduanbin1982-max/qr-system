import json
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_api_facade_has_unique_methods_and_namespaces():
    result = subprocess.run(
        ["node", "frontend/scripts/check-api-facade.mjs"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "namespaces" in result.stdout
    assert "compatibility methods" in result.stdout


def test_frontend_build_runs_api_facade_gate_first():
    root_package = json.loads((PROJECT_ROOT / "package.json").read_text(encoding="utf-8"))
    frontend_package = json.loads(
        (PROJECT_ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
    )

    assert root_package["scripts"]["build"].startswith("npm run check:api &&")
    assert frontend_package["scripts"]["build"].startswith("npm run check:api &&")
