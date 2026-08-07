import ast
import re
from collections import defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IGNORED_PARTS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "backups",
    "data",
    "dist",
    "logs",
    "node_modules",
    "ssl_backup",
    "uploads",
}


def _source_files():
    for path in PROJECT_ROOT.rglob("*.py"):
        relative_parts = set(path.relative_to(PROJECT_ROOT).parts)
        if not relative_parts.intersection(IGNORED_PARTS):
            yield path


def _module_map():
    modules = {}
    packages = set()
    for path in _source_files():
        relative = path.relative_to(PROJECT_ROOT).with_suffix("")
        parts = list(relative.parts)
        if parts[-1] == "__init__":
            module_name = ".".join(parts[:-1])
            packages.add(module_name)
        else:
            module_name = ".".join(parts)
        modules[path] = module_name
    return modules, packages


def _resolve_internal_import(name, known_modules):
    if not (name == "modules" or name.startswith("modules.")):
        return None
    parts = name.split(".")
    while parts:
        candidate = ".".join(parts)
        if candidate in known_modules:
            return candidate
        parts.pop()
    return None


def _dependency_graph():
    modules, packages = _module_map()
    known_modules = set(modules.values()) | packages
    graph = defaultdict(set)

    for path, source_module in modules.items():
        tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
        for node in ast.walk(tree):
            import_names = []
            if isinstance(node, ast.Import):
                import_names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                base_module = node.module
                if node.level:
                    package_parts = source_module.split(".")[: -node.level]
                    base_module = ".".join(package_parts + [node.module])
                import_names.append(base_module)
                for alias in node.names:
                    imported_module = f"{base_module}.{alias.name}"
                    if imported_module in known_modules:
                        import_names.append(imported_module)

            for import_name in import_names:
                target_module = _resolve_internal_import(import_name, known_modules)
                if target_module and target_module != source_module:
                    graph[source_module].add(target_module)

    return graph, known_modules


def _strongly_connected_components(graph, known_modules):
    indices = {}
    lowlinks = {}
    stack = []
    on_stack = set()
    components = []

    def visit(module_name):
        indices[module_name] = len(indices)
        lowlinks[module_name] = indices[module_name]
        stack.append(module_name)
        on_stack.add(module_name)

        for dependency in graph.get(module_name, ()):
            if dependency not in indices:
                visit(dependency)
                lowlinks[module_name] = min(lowlinks[module_name], lowlinks[dependency])
            elif dependency in on_stack:
                lowlinks[module_name] = min(lowlinks[module_name], indices[dependency])

        if lowlinks[module_name] == indices[module_name]:
            component = []
            while True:
                dependency = stack.pop()
                on_stack.remove(dependency)
                component.append(dependency)
                if dependency == module_name:
                    break
            if len(component) > 1:
                components.append(sorted(component))

    for module_name in sorted(known_modules):
        if module_name not in indices:
            visit(module_name)

    return components


def test_backend_modules_have_no_import_cycles():
    graph, known_modules = _dependency_graph()
    cycles = _strongly_connected_components(graph, known_modules)

    assert cycles == [], f"backend import graph contains cycles: {cycles}"

def test_source_files_do_not_have_utf8_bom():
    bom_files = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in _source_files()
        if path.read_bytes().startswith(b"\xef\xbb\xbf")
    ]

    assert bom_files == [], f"source files must be plain UTF-8 without BOM: {bom_files}"


def test_repositories_do_not_depend_on_service_db_helper():
    violations = []
    repository_root = PROJECT_ROOT / "modules" / "repositories"
    for path in sorted(repository_root.glob("*.py")):
        if path.name in {"__init__.py", "context.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imported_names = {alias.name for alias in node.names}
                if module == "modules.db_unit_of_work" and "BaseService" in imported_names:
                    violations.append(path.relative_to(PROJECT_ROOT).as_posix())
                if module == "modules.services" or module.startswith("modules.services."):
                    violations.append(path.relative_to(PROJECT_ROOT).as_posix())

    assert violations == [], f"repositories must depend on repository/context seams, not services: {violations}"


def _imported_modules(path):
    tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.lineno, node.module


def test_domain_layer_has_no_framework_or_infrastructure_dependencies():
    forbidden_prefixes = (
        "flask",
        "modules.app",
        "modules.db",
        "modules.repositories",
        "modules.routes",
        "modules.services",
    )
    violations = []
    for path in sorted((PROJECT_ROOT / "modules" / "domain").rglob("*.py")):
        for lineno, module_name in _imported_modules(path):
            if module_name.startswith(forbidden_prefixes):
                violations.append(
                    f"{path.relative_to(PROJECT_ROOT).as_posix()}:{lineno} -> {module_name}"
                )

    assert violations == [], (
        "domain policy must remain independent of Flask, persistence, routes, and services: "
        f"{violations}"
    )


def test_routes_do_not_depend_on_database_or_repositories():
    forbidden_prefixes = ("modules.db", "modules.repositories")
    violations = []
    for path in sorted((PROJECT_ROOT / "modules" / "routes").rglob("*.py")):
        for lineno, module_name in _imported_modules(path):
            if module_name.startswith(forbidden_prefixes):
                violations.append(
                    f"{path.relative_to(PROJECT_ROOT).as_posix()}:{lineno} -> {module_name}"
                )

    assert violations == [], (
        "routes must call application services instead of persistence details: "
        f"{violations}"
    )


def test_repositories_do_not_depend_on_other_repositories():
    violations = []
    repository_root = PROJECT_ROOT / "modules" / "repositories"
    for path in sorted(repository_root.rglob("*.py")):
        if path.name in {"__init__.py", "context.py"}:
            continue
        relative_parent = path.parent.relative_to(repository_root)
        owned_namespace = None
        if relative_parent.parts:
            owned_namespace = "modules.repositories." + ".".join(relative_parent.parts)
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            module = node.module or ""
            if module.startswith("modules.repositories.") and module != "modules.repositories.context":
                if owned_namespace and module.startswith(owned_namespace + "."):
                    continue
                violations.append(
                    f"{path.relative_to(PROJECT_ROOT).as_posix()} -> {module}"
                )

    assert violations == [], f"repositories must not depend on peer repositories: {violations}"


def test_quality_management_facades_stay_thin():
    service_facade = PROJECT_ROOT / "modules" / "services" / "quality_management_service.py"
    repository_facade = PROJECT_ROOT / "modules" / "repositories" / "quality_management" / "__init__.py"
    legacy_repository = PROJECT_ROOT / "modules" / "repositories" / "quality_management_repository.py"
    expected_service_modules = {
        "base.py", "gates.py", "inspections.py", "nonconformance.py",
        "partners.py", "standards.py", "tasks.py",
    }
    expected_repository_modules = {
        "analytics.py", "inspections.py", "nonconformance.py",
        "partners.py", "standards.py", "tasks.py",
    }

    assert len(service_facade.read_text(encoding="utf-8").splitlines()) < 40
    assert len(repository_facade.read_text(encoding="utf-8").splitlines()) < 40
    assert not legacy_repository.exists()
    assert expected_service_modules.issubset({
        path.name for path in service_facade.parent.joinpath("quality_management").glob("*.py")
    })
    assert expected_repository_modules.issubset({
        path.name for path in repository_facade.parent.glob("*.py")
    })


def test_repositories_do_not_execute_schema_ddl():
    ddl_pattern = re.compile(r"\b(?:CREATE|ALTER|DROP)\s+(?:TABLE|INDEX)\b", re.IGNORECASE)
    violations = []
    repository_root = PROJECT_ROOT / "modules" / "repositories"
    for path in sorted(repository_root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if ddl_pattern.search(node.value):
                    violations.append(
                        f"{path.relative_to(PROJECT_ROOT).as_posix()}:{node.lineno}"
                    )

    assert violations == [], f"schema DDL belongs in migrations, not repositories: {violations}"


def test_report_repositories_use_canonical_product_identity_filter():
    repository_names = (
        "completion_focus_repository.py",
        "reports_repository.py",
        "stats_repository.py",
        "work_time_repository.py",
    )
    for name in repository_names:
        path = PROJECT_ROOT / "modules" / "repositories" / name
        source = path.read_text(encoding="utf-8", errors="replace")
        assert "from modules.product_query import ProductQueryFilter" in source
        assert "ProductQueryFilter.resolve" in source
        assert "product_code_aliases" not in source


def test_process_reporting_policy_delegates_decisions_and_presentation():
    policy_path = PROJECT_ROOT / "modules" / "domain" / "process_reporting.py"
    policy_source = policy_path.read_text(encoding="utf-8", errors="replace")
    presenter_source = (
        PROJECT_ROOT / "modules" / "services" / "process_reporting_presenter.py"
    ).read_text(encoding="utf-8", errors="replace")

    assert len(policy_source.splitlines()) < 100
    assert "ProcessEligibilityPolicy.evaluate" in policy_source
    assert "ProcessSelectionPolicy.select_current" in policy_source
    assert "请先选择当前岗位" not in policy_source
    assert "请先选择当前岗位" in presenter_source


def test_services_do_not_import_sqlite_driver_directly():
    violations = []
    service_root = PROJECT_ROOT / "modules" / "services"
    for path in sorted(service_root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name == "sqlite3" for alias in node.names):
                    violations.append(path.relative_to(PROJECT_ROOT).as_posix())
            elif isinstance(node, ast.ImportFrom) and node.module == "sqlite3":
                violations.append(path.relative_to(PROJECT_ROOT).as_posix())

    assert violations == [], f"service layer must not import sqlite3 directly: {violations}"


def test_services_do_not_depend_on_migrations():
    violations = []
    service_root = PROJECT_ROOT / "modules" / "services"
    for path in sorted(service_root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            imported_modules = []
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.append(node.module)
            for module_name in imported_modules:
                if module_name == "modules.migrations" or module_name.startswith("modules.migration_"):
                    violations.append(
                        f"{path.relative_to(PROJECT_ROOT).as_posix()}:{node.lineno} -> {module_name}"
                    )

    assert violations == [], f"services must not depend on schema migrations: {violations}"


def test_performance_uses_authoritative_quality_evaluation_source():
    performance_paths = (
        PROJECT_ROOT / "modules" / "services" / "performance_fact_collector.py",
        PROJECT_ROOT / "modules" / "services" / "performance_scoring_policy.py",
        PROJECT_ROOT / "modules" / "repositories" / "performance_fact_repository.py",
    )
    forbidden_modules = {
        "modules.services.handoff_review_service",
        "modules.repositories.handoff_review_repository",
    }
    violations = []
    for path in performance_paths:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
        if "process_handoff_reviews" in source:
            violations.append(f"{path.relative_to(PROJECT_ROOT).as_posix()} -> legacy table")
        for node in ast.walk(tree):
            imported_modules = []
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.append(node.module)
            for module_name in imported_modules:
                if module_name in forbidden_modules:
                    violations.append(
                        f"{path.relative_to(PROJECT_ROOT).as_posix()}:{node.lineno} -> {module_name}"
                    )

    performance_source = performance_paths[0].read_text(encoding="utf-8", errors="replace")
    assert "PerformanceFactRepository.list_quality_events" in performance_source
    assert violations == [], (
        "performance scoring must use process_quality_evaluations as its authoritative source: "
        f"{violations}"
    )


def test_performance_fact_repository_uses_only_canonical_quality_sources():
    path = PROJECT_ROOT / "modules" / "repositories" / "performance_fact_repository.py"
    source = path.read_text(encoding="utf-8", errors="replace")

    assert "performance_quality_events" in source
    assert "performance_quality_event_sources" in source
    assert "process_handoff_reviews" not in source


def test_services_do_not_embed_sql_statements():
    sql_pattern = re.compile(
        r"\b(?:SELECT\b.+\bFROM|INSERT\s+INTO|UPDATE\s+[A-Za-z_]\w*\s+SET|DELETE\s+FROM)\b",
        re.IGNORECASE | re.DOTALL,
    )
    violations = []
    for path in sorted((PROJECT_ROOT / "modules" / "services").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if sql_pattern.search(node.value):
                    violations.append(
                        f"{path.relative_to(PROJECT_ROOT).as_posix()}:{node.lineno}"
                    )

    assert violations == [], f"service layer must pass business filters, not SQL: {violations}"


def test_auth_middleware_delegates_session_persistence():
    path = PROJECT_ROOT / "modules" / "middleware" / "auth.py"
    source = path.read_text(encoding="utf-8", errors="replace")

    assert "get_db" not in source
    assert ".execute(" not in source
    assert ".commit(" not in source
    assert ".rollback(" not in source
    assert "AuthSessionService.authenticate" in source


def test_shipment_repository_only_owns_shipment_tables():
    path = PROJECT_ROOT / "modules" / "repositories" / "shipment_repository.py"
    source = path.read_text(encoding="utf-8", errors="replace").upper()
    forbidden = (
        "FROM ORDERS", "UPDATE ORDERS", "FROM INVENTORY", "UPDATE INVENTORY",
        "INSERT INTO INVENTORY", "FROM PRODUCTS", "UPDATE PRODUCTS",
    )

    assert not [token for token in forbidden if token in source]

def test_access_policy_core_has_no_repository_dependency():
    path = PROJECT_ROOT / "modules" / "access_policy.py"
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("modules.repositories"):
            violations.append(node.module)
        elif isinstance(node, ast.Import):
            violations.extend(alias.name for alias in node.names if alias.name.startswith("modules.repositories"))

    assert violations == []
