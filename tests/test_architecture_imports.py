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


def test_repositories_do_not_depend_on_other_repositories():
    violations = []
    repository_root = PROJECT_ROOT / "modules" / "repositories"
    for path in sorted(repository_root.glob("*.py")):
        if path.name in {"__init__.py", "context.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            module = node.module or ""
            if module.startswith("modules.repositories.") and module != "modules.repositories.context":
                violations.append(
                    f"{path.relative_to(PROJECT_ROOT).as_posix()} -> {module}"
                )

    assert violations == [], f"repositories must not depend on peer repositories: {violations}"


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
