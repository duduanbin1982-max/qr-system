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


def test_frontend_source_graph_has_no_import_cycles():
    result = subprocess.run(
        ["node", "frontend/scripts/check-import-cycles.mjs"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "import cycle check passed" in result.stdout


def test_production_facade_exposes_legacy_lines_as_read_only_compatibility():
    production_api = (
        PROJECT_ROOT / "frontend" / "src" / "lib" / "api" / "production.js"
    ).read_text(encoding="utf-8")

    assert "listProductionLines" in production_api
    assert "createProductionLine" not in production_api
    assert "updateProductionLine" not in production_api
    assert "deleteProductionLine" not in production_api


def test_frontend_build_checks_toolchain_then_api_before_compilation():
    root_package = json.loads((PROJECT_ROOT / "package.json").read_text(encoding="utf-8"))

    steps = [step.strip() for step in root_package["scripts"]["build"].split("&&")]
    assert steps[:2] == [
        "node frontend/scripts/check-toolchain.mjs", "npm run check:api",
    ]
    assert steps[-1] == "vite build"
    assert not (PROJECT_ROOT / "frontend" / "package.json").exists()


def test_frontend_layer_gate_runs_in_architecture_and_production_build():
    root_package = json.loads((PROJECT_ROOT / "package.json").read_text(encoding="utf-8"))
    scripts = root_package["scripts"]

    for entrypoint in ("build", "check:architecture"):
        assert "npm run check:layers" in scripts[entrypoint]
    assert "node --test frontend/tests/architecture/frontend-layers.test.mjs" in scripts["check:layers"]
    assert "node frontend/scripts/check-frontend-layers.mjs" in scripts["check:layers"]


def test_process_quality_page_only_loads_stats_with_permission():
    page = (
        PROJECT_ROOT / "frontend" / "src" / "views" / "ProcessQualityEvaluationPage.vue"
    ).read_text(encoding="utf-8")
    composable = (
        PROJECT_ROOT
        / "frontend"
        / "src"
        / "composables"
        / "quality"
        / "useProcessQualityEvaluation.js"
    ).read_text(encoding="utf-8")

    assert (
        "import { useProcessQualityEvaluation } from "
        "'@/composables/quality/useProcessQualityEvaluation.js'"
    ) in page
    assert "} = useProcessQualityEvaluation()" in page
    assert "if (can('process_quality_evaluation:stats')) await loadStats()" in composable


def test_frontend_client_uses_cookie_auth_and_domain_error_shape():
    client = (
        PROJECT_ROOT / "frontend" / "src" / "lib" / "api" / "client.js"
    ).read_text(encoding="utf-8")

    assert "credentials: 'same-origin'" in client
    assert "Authorization" not in client
    assert "Bearer " not in client
    for field in (
        "error.code",
        "error.status",
        "error.domainCode",
        "error.action",
        "error.details",
        "error.payload",
    ):
        assert field in client
    assert "response.status === 409" in client
    assert "auth:expired" in client


def test_frontend_does_not_persist_or_append_session_tokens():
    auth_source = (
        PROJECT_ROOT / "frontend" / "src" / "lib" / "auth.js"
    ).read_text(encoding="utf-8")
    product_source = (
        PROJECT_ROOT / "frontend" / "src" / "composables" / "useProduct.js"
    ).read_text(encoding="utf-8")
    product_view = (
        PROJECT_ROOT / "frontend" / "src" / "views" / "ProductList.vue"
    ).read_text(encoding="utf-8")

    assert "delete user.token" in auth_source
    assert "?token=" not in product_source
    assert "?token=" not in product_view
    assert "auth.token" not in product_source
    assert "auth.token" not in product_view
