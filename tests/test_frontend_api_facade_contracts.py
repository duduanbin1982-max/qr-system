import json
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_api_facade_has_unique_domain_methods_and_no_flat_calls():
    result = subprocess.run(
        ["node", "frontend/scripts/check-api-facade.mjs"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "namespaces" in result.stdout
    assert "unique domain methods" in result.stdout


def test_frontend_build_runs_api_facade_gate_first():
    root_package = json.loads((PROJECT_ROOT / "package.json").read_text(encoding="utf-8"))

    assert root_package["scripts"]["build"].startswith("npm run check:api &&")
    assert not (PROJECT_ROOT / "frontend" / "package.json").exists()


def test_process_quality_page_only_loads_stats_with_permission():
    page = (
        PROJECT_ROOT / "frontend" / "src" / "views" / "ProcessQualityEvaluationPage.vue"
    ).read_text(encoding="utf-8")

    assert "if (can('process_quality_evaluation:stats')) await loadStats()" in page
